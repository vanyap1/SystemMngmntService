"""Top bar navigation registry: the work sections of the panel, each with one or more pages.

A section with several pages shows them as sub-tabs while one of its pages is open (e.g. Tests → Run / Logs);
otherwise the section links to its first visible page. Add a page to an existing section, or a new Section.
Global tools (Monitor, Devices, Services, Settings, power menu) are not sections — see templates/base.html.
"""
from collections import namedtuple

# public: True = everyone, False = login only, or a feature of auth.can() ('tests', 'docs', 'backups').
NavItem = namedtuple('NavItem', 'endpoint label icon public')
Section = namedtuple('Section', 'id label icon items')

SECTIONS = [
    Section('main', 'Main', 'fa-solid fa-house', [
        NavItem('dashboard.index', 'Main', 'fa-solid fa-house', True),
    ]),
    Section('code', 'Code', 'fa-solid fa-code', [
        NavItem('editor.editor', 'Code Editor', 'fa-solid fa-code', False),
    ]),
    Section('ui', 'UI', 'fa-solid fa-object-group', [
        NavItem('uidesign.page', 'UI designer', 'fa-solid fa-object-group', False),
    ]),
    Section('docs', 'Docs', 'fa-solid fa-book', [
        NavItem('help.help_page', 'Docs', 'fa-solid fa-book', 'docs'),
    ]),
    Section('tests', 'Tests', 'fa-solid fa-vial', [
        NavItem('tests.tests', 'Run', 'fa-solid fa-play', 'tests'),
        NavItem('logs.logs', 'Logs', 'fa-solid fa-file-lines', 'tests'),
    ]),
]

SETTINGS = NavItem('settings.settings', 'Settings', 'fa-solid fa-gear', False)


def _visible(item, logged_in):
    if logged_in or item.public is True:
        return True
    if not item.public:
        return False
    from core import auth
    return auth.public_can(item.public)


def sections(logged_in, current_endpoint):
    """Sections visible to this visitor: [{id, label, icon, endpoint, active, pages: [{endpoint, label, icon, active}]}]."""
    from core import config
    tests_home = not logged_in and config.public_access()['home'] == 'tests'
    out = []
    for s in SECTIONS:
        items = []
        for i in s.items:
            if not _visible(i, logged_in):
                continue
            ep = i.endpoint
            if ep == 'dashboard.index' and tests_home:
                ep = 'dashboard.main'                  # "/" leads to the Tests page for this visitor
            items.append({'endpoint': ep, 'label': i.label, 'icon': i.icon,
                          'active': current_endpoint in (i.endpoint, ep)})
        if items:
            out.append({'id': s.id, 'label': s.label, 'icon': s.icon, 'endpoint': items[0]['endpoint'],
                        'active': any(i['active'] for i in items), 'pages': items})
    return out


def endpoints():
    """Every page endpoint in the navigation (for tests)."""
    return [i.endpoint for s in SECTIONS for i in s.items] + [SETTINGS.endpoint]
