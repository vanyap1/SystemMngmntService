"""Git of the panel's repositories (Settings → Git, Git popup in the editor and docs). Login only.
The token is write-only: it is stored by core/credentials.py and never returned."""
from flask import Blueprint, jsonify, request

from core import credentials, git_ops
from core.auth import login_required
from core.git_ops import GitError

bp = Blueprint('git', __name__)


@bp.errorhandler(GitError)
def _git_error(e):
    return jsonify({'error': str(e), 'output': e.output}), e.status


def _body():
    return request.get_json(silent=True) or {}


def _repo(d=None):
    rid = (d or {}).get('repo') if d is not None else request.args.get('repo')
    return git_ops.Repo(rid or 'project')


def _done(repo, message):
    return jsonify({'ok': True, 'message': message, 'overview': repo.overview()})


@bp.route('/api/git/repos')
@login_required
def api_repos():
    return jsonify({'repos': [{'id': r['id'], 'label': r['label'], 'path': r['path'], 'top': r['top'],
                               'aliases': r['aliases']} for r in git_ops.repos()]})


@bp.route('/api/git/tree_status')
@login_required
def api_tree_status():
    """Changed files of target_dir's repositories for the code editor's file tree."""
    return jsonify(git_ops.tree_status())


@bp.route('/api/git/clone', methods=['POST'])
@login_required
def api_clone():
    d = _body()
    res = git_ops.clone(d.get('url'), d.get('name'))
    return jsonify({'ok': True, 'message': f'Cloned into {res["path"]}', 'repo': res['repo']})


@bp.route('/api/git/init', methods=['POST'])
@login_required
def api_init():
    res = git_ops.init_target()
    return jsonify({'ok': True, 'message': f'Initialized {res["path"]}', 'repo': res['repo']})


@bp.route('/api/git/status')
@login_required
def api_status():
    return jsonify(_repo().overview())


@bp.route('/api/git/summary')
@login_required
def api_summary():
    """Cheap badge info for the toolbar icons: changed files, ahead/behind, problems."""
    try:
        r = _repo()
    except GitError as e:
        return jsonify({'error': str(e)}), 200
    st = r.status()
    probs = r.problems(st)
    return jsonify({'branch': st['branch'], 'changes': len(st['files']), 'ahead': st['ahead'], 'behind': st['behind'],
                    'errors': sum(p['level'] == 'error' for p in probs), 'warnings': sum(p['level'] == 'warn' for p in probs)})


@bp.route('/api/git/diff')
@login_required
def api_diff():
    return jsonify({'diff': _repo().diff(request.args.get('path', ''))})


@bp.route('/api/git/commit', methods=['POST'])
@login_required
def api_commit():
    d = _body()
    r = _repo(d)
    paths = d.get('paths')
    if paths is not None and not isinstance(paths, list):
        raise GitError('Bad paths')
    msg = 'Committed ' + r.commit(d.get('message', ''), paths, (d.get('new_branch') or '').strip() or None)
    if d.get('push'):
        msg += '\n' + (r.push() or 'pushed')
    return _done(r, msg)


@bp.route('/api/git/branch', methods=['POST'])
@login_required
def api_branch():
    d = _body()
    r = _repo(d)
    return _done(r, 'Created branch ' + r.create_branch(d.get('name', ''), d.get('checkout', True) is not False))


@bp.route('/api/git/checkout', methods=['POST'])
@login_required
def api_checkout():
    d = _body()
    r = _repo(d)
    return _done(r, 'Switched to ' + r.checkout(d.get('branch', '')))


@bp.route('/api/git/branch_delete', methods=['POST'])
@login_required
def api_branch_delete():
    d = _body()
    r = _repo(d)
    return _done(r, 'Deleted branch ' + r.delete_branch(d.get('branch', ''), bool(d.get('force'))))


@bp.route('/api/git/fetch', methods=['POST'])
@login_required
def api_fetch():
    r = _repo(_body())
    return _done(r, r.fetch())


@bp.route('/api/git/pull', methods=['POST'])
@login_required
def api_pull():
    d = _body()
    r = _repo(d)
    return _done(r, r.pull(d.get('mode', 'ff')) or 'Already up to date')


@bp.route('/api/git/push', methods=['POST'])
@login_required
def api_push():
    d = _body()
    r = _repo(d)
    return _done(r, r.push(bool(d.get('force_lease'))) or 'Pushed')


@bp.route('/api/git/discard', methods=['POST'])
@login_required
def api_discard():
    d = _body()
    r = _repo(d)
    paths = d.get('paths')
    if not isinstance(paths, list) or not paths:
        raise GitError('No files')
    return _done(r, f'Discarded {r.discard(paths)} file(s)')


@bp.route('/api/git/reset', methods=['POST'])
@login_required
def api_reset():
    r = _repo(_body())
    return _done(r, r.reset_to_upstream())


@bp.route('/api/git/fix', methods=['POST'])
@login_required
def api_fix():
    d = _body()
    r = _repo(d)
    return _done(r, r.fix(d.get('id', '')))


@bp.route('/api/git/identity', methods=['POST'])
@login_required
def api_identity():
    d = _body()
    r = _repo(d)
    r.set_identity(d.get('name'), d.get('email'), d.get('scope', 'local'))
    return _done(r, 'Identity saved')


@bp.route('/api/git/credentials', methods=['GET', 'POST'])
@login_required
def api_credentials():
    if request.method == 'POST':
        d = _body()
        token = '' if d.get('clear_token') else (d.get('token') or None)   # empty field = keep the token
        username = d.get('username')
        if username is not None and not isinstance(username, str) or token is not None and not isinstance(token, str):
            raise GitError('Bad data')
        credentials.set_git(username, token)
    return jsonify(credentials.public())
