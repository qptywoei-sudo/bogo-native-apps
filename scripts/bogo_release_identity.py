"""Identity of the next immutable Bogo release, separate from legacy versions."""
import re

# Revision 1 already has publicly downloaded Design/Grid installers. A changed
# application is a new release; those files and their original hashes stay fixed.
CURRENT_REVISION = 2


def release_version(upstream):
    if not isinstance(upstream, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', upstream):
        raise ValueError('Expected the exact pinned three-part upstream version')
    return upstream + '-bogo.' + str(CURRENT_REVISION)


def approved_promotion_transition(app, relative, before, after):
    # The user explicitly removed these auxiliary project-link registrations.
    # Match complete source identities; no other engine/document/license file
    # receives an exception and a rehashed manifest cannot expand this set.
    from bogo_promotion_removal import protected_transition_allowed as main_allowed
    from bogo_promotion_four import protected_transition_allowed as four_allowed
    return main_allowed(app, relative, before, after) or four_allowed(app, relative, before, after)


def promotion_transition_records(app):
    import bogo_promotion_removal as main
    import bogo_promotion_four as four
    records = []
    seen = set()
    for module in (main, four):
        for (selected, relative), old in sorted(module.PROTECTED_BEFORE.items()):
            if selected != app:
                continue
            if relative in seen:
                raise ValueError('Duplicate protected promotion transition')
            seen.add(relative)
            new = module.PROTECTED_AFTER[selected, relative]
            records.append({'path': relative,
                            'before': {'sha256': old[0], 'bytes': old[1]},
                            'after': {'sha256': new[0], 'bytes': new[1]},
                            'scope': 'user-requested retired promotion metadata or built-in sample URL; document/media functions and legal notices preserved'})
    return sorted(records, key=lambda row: row['path'])
