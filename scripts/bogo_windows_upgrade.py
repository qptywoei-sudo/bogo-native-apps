"""Narrow MSI upgrade discovery from unchanged, existing HKLM App Paths.

RegistrySearch Type=file without FileSearch returns the containing directory;
explicit old/new FileSearch signatures verify the executable before adopting it.
See https://docs.firegiant.com/wix/schema/wxs/registrysearch/ .
This adds read-only searches, never registry values, keys, GUIDs or relocations.
"""
from collections import Counter
import copy
from pathlib import Path
import xml.etree.ElementTree as ET

NS = {"w": "http://wixtoolset.org/schemas/v4/wxs"}
APPS = {
    "cad": ("cadcraft", "Cad", "CAD"), "design": ("designcraft", "Design", "Design"),
    "film": ("filmcraft", "Film", "Film"), "pdf": ("pdfcraft", "PDF", "PDF"),
    "word": ("wordcraft", "Word", "Word"), "sound": ("soundcraft", "Sound", "Sound"),
    "deck": ("deckcraft", "Deck", "Deck"), "grid": ("gridcraft", "Grid", "Grid"),
    "light": ("lightcraft", "Light", "Light"),
}
NEW_FOLDER_PROPERTY = "BOGOPREVIOUSAPPFOLDER"
OLD_EXE_PROPERTY = "BOGOPREVIOUSAPPEXE"
NEW_EXE_PROPERTY = "BOGOCURRENTAPPEXE"
FOLDER_CONDITION = "NOT INSTALLFOLDER AND BOGOPREVIOUSAPPFOLDER AND (BOGOPREVIOUSAPPEXE OR BOGOCURRENTAPPEXE)"


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Unreviewed Windows upgrade source: " + before[:100])
    return text.replace(before, after, 1)


def app_key(app):
    return "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\KIO " + APPS[app][1] + ".exe"


def additions(app):
    """Exact additive WiX declarations consumed by the transition auditor."""
    if app not in APPS:
        return ""
    key = app_key(app)
    if app == "light":
        return f'''    <Property Id="BOGOCURRENTLIGHTEXE" Secure="yes">
      <RegistrySearch Id="BogoCurrentLightExe" Root="HKLM" Key="{key}" Type="file" Bitness="always64">
        <FileSearch Id="BogoCurrentLightExeFile" Name="Bogo Light.exe" />
      </RegistrySearch>
    </Property>
'''
    old, new = "KIO " + APPS[app][1] + ".exe", "Bogo " + APPS[app][2] + ".exe"
    block = f'''    <!-- Reuse an existing custom folder only after an exact old/new executable is found. -->
    <Property Id="{NEW_FOLDER_PROPERTY}" Secure="yes">
      <RegistrySearch Id="BogoPreviousAppFolder" Root="HKLM" Key="{key}" Type="file" Bitness="always64" />
    </Property>
    <Property Id="{OLD_EXE_PROPERTY}" Secure="yes">
      <RegistrySearch Id="BogoPreviousAppExe" Root="HKLM" Key="{key}" Type="file" Bitness="always64">
        <FileSearch Id="BogoPreviousAppExeFile" Name="{old}" />
      </RegistrySearch>
    </Property>
    <Property Id="{NEW_EXE_PROPERTY}" Secure="yes">
      <RegistrySearch Id="BogoCurrentAppExe" Root="HKLM" Key="{key}" Type="file" Bitness="always64">
        <FileSearch Id="BogoCurrentAppExeFile" Name="{new}" />
      </RegistrySearch>
    </Property>
    <SetProperty Id="INSTALLFOLDER" Action="BogoSetExistingAppFolder" Value="[{NEW_FOLDER_PROPERTY}]"
        After="AppSearch" Sequence="both" Condition="{FOLDER_CONDITION}" />
'''
    if app == "pdf":
        block += '''    <Property Id="BOGOCURRENTDESKTOPSHORTCUT">
      <DirectorySearch Id="BogoCurrentPdfDesktop" Path="[DesktopFolder]" Depth="0">
        <FileSearch Id="BogoCurrentPdfDesktopFile" Name="Bogo PDF.lnk" />
      </DirectorySearch>
    </Property>
'''
    return block


def _signature(element):
    return (element.tag, tuple(sorted(element.attrib.items())), tuple(_signature(child) for child in element))


def _wrapper(block):
    return ET.fromstring('<Package xmlns="' + NS["w"] + '">' + block + '</Package>')


def expected_additive_registry_searches(app):
    return {e.get("Id"): _signature(e) for e in _wrapper(additions(app)).findall('.//w:RegistrySearch', NS)}


def validate_additive_searches(before, after, app):
    """Reject any unapproved changed/added search, property, action or file guard.

    `before` must be the authenticated legacy WiX root; `after` the Bogo root.
    Every old search (including child file signatures) must remain identical.
    """
    expected = _wrapper(additions(app))
    names = ("RegistrySearch", "DirectorySearch", "FileSearch")
    for name in names:
        old = Counter(_signature(e) for e in before.findall('.//w:' + name, NS))
        new = Counter(_signature(e) for e in after.findall('.//w:' + name, NS))
        added = Counter(_signature(e) for e in expected.findall('.//w:' + name, NS))
        if new != old + added:
            raise ValueError("Unapproved MSI search change: " + app + "/" + name)
    old_properties = before.findall('.//w:Property', NS)
    new_properties = after.findall('.//w:Property', NS)
    extra_properties = expected.findall('.//w:Property', NS)
    if Counter(e.get('Id') for e in new_properties) != Counter(e.get('Id') for e in old_properties) + Counter(e.get('Id') for e in extra_properties):
        raise ValueError("Unapproved MSI property identity addition/change")
    def searched_property(e):
        return e.get('Id') == 'INSTALLFOLDER' or any(e.findall('.//w:' + name, NS) for name in names)
    if Counter(_signature(e) for e in new_properties if searched_property(e)) != Counter(_signature(e) for e in old_properties if searched_property(e)) + Counter(_signature(e) for e in extra_properties if searched_property(e)):
        raise ValueError("Unapproved MSI search property wrapper change")
    old_setters = [copy.deepcopy(e) for e in before.findall('.//w:SetProperty', NS)]
    for e in old_setters:
        if app == 'light' and e.get('Action') == 'SetInstallFolderFromAppPaths':
            e.set('Condition', 'LEGACYINSTALLFOLDER AND (LEGACYINSTALLEXE OR BOGOCURRENTLIGHTEXE) AND NOT PREVIOUSINSTALLFOLDER AND NOT INSTALLFOLDER')
        if app == 'pdf' and e.get('Id') == 'INSTALLDESKTOPSHORTCUT':
            e.set('Condition', 'NOT INSTALLDESKTOPSHORTCUT AND (NOT WIX_UPGRADE_DETECTED OR EXISTINGDESKTOPSHORTCUT OR BOGOCURRENTDESKTOPSHORTCUT)')
    if Counter(_signature(e) for e in after.findall('.//w:SetProperty', NS)) != Counter(_signature(e) for e in old_setters) + Counter(_signature(e) for e in expected.findall('.//w:SetProperty', NS)):
        raise ValueError("Unapproved MSI scheduled property action change")
    package = after.find('w:Package', NS) if after.tag.endswith('Wix') else after
    for declaration in expected:
        if not any(_signature(child) == _signature(declaration) for child in package):
            raise ValueError("Missing exact MSI upgrade declaration: " + str(declaration.attrib))
    if app == "light":
        conditions = [e.get("Condition") for e in after.findall('.//w:SetProperty', NS) if e.get('Action') == 'SetInstallFolderFromAppPaths']
        if conditions != ["LEGACYINSTALLFOLDER AND (LEGACYINSTALLEXE OR BOGOCURRENTLIGHTEXE) AND NOT PREVIOUSINSTALLFOLDER AND NOT INSTALLFOLDER"]:
            raise ValueError("Light upgrade precedence/existence guards changed")
    if app == "pdf":
        conditions = [e.get("Condition") for e in after.findall('.//w:SetProperty', NS) if e.get('Id') == 'INSTALLDESKTOPSHORTCUT']
        if conditions != ["NOT INSTALLDESKTOPSHORTCUT AND (NOT WIX_UPGRADE_DETECTED OR EXISTINGDESKTOPSHORTCUT OR BOGOCURRENTDESKTOPSHORTCUT)"]:
            raise ValueError("PDF desktop shortcut precedence changed")
    return {"app": app, "additiveRegistrySearchIds": sorted(expected_additive_registry_searches(app)),
            "originalSearchesUnchanged": True, "newStoredRegistryKeys": False,
            "actualMsiExecution": "not-performed"}


def transform_windows_upgrade(source, app):
    if app not in APPS:
        return []
    path = Path(source) / "packaging/windows" / (APPS[app][0] + ".wxs")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing regular MSI source: " + str(path))
    text = path.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    package = root.find('w:Package', NS)
    registrations = [e for e in root.findall('.//w:RegistryValue', NS)
                     if e.get('Root') == 'HKLM' and e.get('Key') == app_key(app) and e.get('Name') is None]
    if package is None or package.get('Scope') != 'perMachine' or len(registrations) != 1:
        raise ValueError("Unreviewed App Paths scope/identity: " + app)
    app_files = [e for e in root.findall('.//w:File', NS)
                 if e.get('Source', '').endswith('\\' + APPS[app][0] + '.exe')]
    names = {"KIO " + APPS[app][1] + ".exe", "Bogo " + APPS[app][2] + ".exe"}
    if len(app_files) != 1 or app_files[0].get('Name') not in names or registrations[0].get('Value') != '[#' + app_files[0].get('Id', '') + ']':
        raise ValueError("Unreviewed App Paths executable binding: " + app)
    if any(e.get('Id', '').startswith('BogoPreviousApp') or e.get('Id') == 'BogoCurrentLightExe'
           for e in root.findall('.//w:RegistrySearch', NS)):
        raise ValueError("MSI upgrade discovery already applied")
    if app == "light":
        # Generic visible branding must not rename this historical file signature.
        if '<FileSearch Id="LegacyInstallExeFile" Name="Bogo Light.exe" />' in text:
            text = replace_once(text, '<FileSearch Id="LegacyInstallExeFile" Name="Bogo Light.exe" />', '<FileSearch Id="LegacyInstallExeFile" Name="KIO Light.exe" />')
        if '<FileSearch Id="LegacyInstallExeFile" Name="KIO Light.exe" />' not in text:
            raise ValueError("Missing Light legacy existence search")
        text = replace_once(text, '    <SetProperty Id="INSTALLFOLDER" Action="SetInstallFolderFromAppPaths"', additions(app) + '    <SetProperty Id="INSTALLFOLDER" Action="SetInstallFolderFromAppPaths"')
        text = replace_once(text, 'LEGACYINSTALLFOLDER AND LEGACYINSTALLEXE AND NOT PREVIOUSINSTALLFOLDER AND NOT INSTALLFOLDER', 'LEGACYINSTALLFOLDER AND (LEGACYINSTALLEXE OR BOGOCURRENTLIGHTEXE) AND NOT PREVIOUSINSTALLFOLDER AND NOT INSTALLFOLDER')
    else:
        marker = text.index('    <StandardDirectory ')
        text = text[:marker] + additions(app) + text[marker:]
        if app == 'cad':
            text = replace_once(text, 'Target="[INSTALLFOLDER]cadcraft.exe"', 'Target="[#CadcraftExe]"')
        if app == 'pdf':
            if '<FileSearch Name="Bogo PDF.lnk" />' in text:
                text = replace_once(text, '<FileSearch Name="Bogo PDF.lnk" />', '<FileSearch Name="KIO PDF.lnk" />')
            if '<FileSearch Name="KIO PDF.lnk" />' not in text:
                raise ValueError("Missing PDF historical desktop shortcut search")
            text = replace_once(text, 'NOT INSTALLDESKTOPSHORTCUT AND (NOT WIX_UPGRADE_DETECTED OR EXISTINGDESKTOPSHORTCUT)', 'NOT INSTALLDESKTOPSHORTCUT AND (NOT WIX_UPGRADE_DETECTED OR EXISTINGDESKTOPSHORTCUT OR BOGOCURRENTDESKTOPSHORTCUT)')
    ET.fromstring(text)  # Refuse malformed authoring before writing anything.
    path.write_text(text, encoding="utf-8")
    return [path.relative_to(source).as_posix()]
