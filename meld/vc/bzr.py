### Copyright (C) 2002-2005 Stephen Kennedy <stevek@gnome.org>
### Copyright (C) 2005 Aaron Bentley <aaron.bentley@utoronto.ca>

### Redistribution and use in source and binary forms, with or without
### modification, are permitted provided that the following conditions
### are met:
### 
### 1. Redistributions of source code must retain the above copyright
###    notice, this list of conditions and the following disclaimer.
### 2. Redistributions in binary form must reproduce the above copyright
###    notice, this list of conditions and the following disclaimer in the
###    documentation and/or other materials provided with the distribution.

### THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
### IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
### OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
### IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
### INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
### NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
### DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
### THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
### (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
### THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import errno
import os
import re
import shutil
import subprocess
import tempfile

from . import _vc


class Vc(_vc.CachedVc):

    CMD = "bzr"
    CMDARGS = ["--no-aliases", "--no-plugins"]
    NAME = "Bazaar"
    VC_DIR = ".bzr"
    PATCH_INDEX_RE = "^=== modified file '(.*)' (.*)$"
    CONFLICT_RE = "conflict in (.*)$"
    RENAMED_RE = ".*=> (.*)$"
    commit_statuses = (
        _vc.STATE_MODIFIED, _vc.STATE_RENAMED, _vc.STATE_NEW, _vc.STATE_REMOVED
    )

    VC_COLUMNS = (_vc.DATA_NAME, _vc.DATA_STATE, _vc.DATA_OPTIONS)

    conflict_map = {
        _vc.CONFLICT_BASE: '.BASE',
        _vc.CONFLICT_OTHER: '.OTHER',
        _vc.CONFLICT_THIS: '.THIS',
        _vc.CONFLICT_MERGED: '',
    }

    # We use None here to indicate flags that we don't deal with or care about
    state_1_map = {
        " ": None,                # First status column empty
        "+": None,                # File versioned
        "-": None,                # File unversioned
        "R": _vc.STATE_RENAMED,   # File renamed
        "?": _vc.STATE_NONE,      # File unknown
        "X": None,                # File nonexistent (and unknown to bzr)
        "C": _vc.STATE_CONFLICT,  # File has conflicts
        "P": None,                # Entry for a pending merge (not a file)
    }

    state_2_map = {
        " ": _vc.STATE_NORMAL,    # Second status column empty
        "N": _vc.STATE_NEW,       # File created
        "D": _vc.STATE_REMOVED,   # File deleted
        "K": _vc.STATE_RENAMED,   # File kind changed
        "M": _vc.STATE_MODIFIED,  # File modified
    }

    # BZR only tracks executable bit changes.
    state_3_map = {
        " ": None,  # Third status column empty
        "*": _vc.STATE_MODIFIED,  # File x bit changed
        "/": _vc.STATE_MODIFIED,  # Dir x bit changed # Can't test?
        "@": _vc.STATE_MODIFIED,  # Symlink x bit changed # Impossible?
    }

    valid_status_re = r'[%s][%s][%s]\s*' % (''.join(state_1_map.keys()),
                                            ''.join(state_2_map.keys()),
                                            ''.join(state_3_map.keys()),)

    def __init__(self, location):
        super(Vc, self).__init__(location)
        self._tree_meta_cache = {}

    def commit_command(self, message):
        return [self.CMD] + self.CMDARGS + ["commit", "-m", message]

    def add_command(self):
        return [self.CMD] + self.CMDARGS + ["add"]

    def revert(self, runner, files):
        runner(
            [self.CMD] + self.CMDARGS + ["revert"] + files, [], refresh=True,
            working_dir=self.root)

    def push(self, runner):
        runner(
            [self.CMD] + self.CMDARGS + ["push"], [], refresh=True,
            working_dir=self.root)

    def update(self, runner, files):
        # TODO: Handle checkouts/bound branches by calling
        # update instead of pull. For now we've replicated existing
        # functionality, as update will not work for unbound branches.
        runner(
            [self.CMD] + self.CMDARGS + ["pull"], [], refresh=True,
            working_dir=self.root)

    def resolve(self, runner, files):
        runner(
            [self.CMD] + self.CMDARGS + ["resolve"] + files, [], refresh=True,
            working_dir=self.root)

    def remove(self, runner, files):
        runner(
            [self.CMD] + self.CMDARGS + ["rm"] + files, [], refresh=True,
            working_dir=self.root)

    @classmethod
    def valid_repo(cls, path):
        return not _vc.call([cls.CMD, "root"], cwd=path)

    def get_working_directory(self, workdir):
        return self.root

    def get_files_to_commit(self, paths):
        files = []
        for p in paths:
            if os.path.isdir(p):
                entries = self._lookup_tree_cache(p)
                names = [
                    x for x, y in entries.items() if y in self.commit_statuses]
                files.extend(names)
            else:
                files.append(os.path.relpath(p, self.root))
        return sorted(list(set(files)))

    def get_commits_to_push_summary(self):
        """
         Returns the output from bzr missing --mine-only

         Could also check bzr missing --theirs-only - and return an error
         if it gives results, as a merge would be required first.
        """
        # XXX Until we make this async we can't use this.
        return ''
        # proc = _vc.popen(
        #     [self.CMD, "missing", '--mine-only', '--line'], cwd=self.location)
        # return proc.readlines()[1]

    def _get_modified_files(self, path):
        # Get the status of files that have changed
        proc = _vc.popen(
            # Maybe add a -V
            [self.CMD] + self.CMDARGS + ["status", "-S", "--no-pending", path],
            cwd=self.location)
        entries = proc.read().split("\n")[:-1]
        entries = list(set(entries))

        return entries

    def _update_tree_state_cache(self, path, tree_state):
        """ Update the state of the file(s) at tree_state['path'] """
        while 1:
            try:
                entries = self._get_modified_files(path)
                break
            except OSError as e:
                if e.errno != errno.EAGAIN:
                    raise

        if len(entries) == 0 and os.path.isfile(path):
            # If we're just updating a single file there's a chance that it
            # was it was previously modified, and now has been edited
            # so that it is un-modified.  This will result in an empty
            # 'entries' list, and tree_state['path'] will still contain stale
            # data.  When this corner case occurs we force tree_state['path']
            # to STATE_NORMAL.
            tree_state[path] = _vc.STATE_NORMAL
        else:
            branch_root = _vc.popen(
                [self.CMD] + self.CMDARGS + ["root", self.location]
            ).read().rstrip('\n')
            for entry in entries:
                state_string, name = entry[:3], entry[4:].strip()
                meta = ''
                if not re.match(self.valid_status_re, state_string):
                    continue
                state = self.state_1_map.get(state_string[0], None)
                if state is None:
                    state = self.state_2_map.get(
                        state_string[1], _vc.STATE_NORMAL)

                # Renamed and conflicts need some extra processing.
                if state == _vc.STATE_RENAMED:
                    # Need to do some more matching to get the new filename
                    real_path_match = re.search(self.RENAMED_RE, name)
                    if real_path_match is None:
                        continue
                    meta += name
                    # If this was renamed to a directory, strip the slash.
                    name = real_path_match.group(1).strip('/')
                elif state == _vc.STATE_CONFLICT:
                    real_path_match = re.search(self.CONFLICT_RE, name)
                    if real_path_match is None:
                        continue
                    name = real_path_match.group(1)

                path = os.path.join(branch_root, name)

                executable_change = self.state_3_map.get(state_string[2], None)
                if executable_change is not None:
                    if state is _vc.STATE_NORMAL:
                        state = executable_change
                    # Find current executable status changes by diffing the file
                    line = _vc.popen(['bzr', 'diff', path]).readline()
                    executable_match = re.search(self.PATCH_INDEX_RE, line)
                    if executable_match:
                        meta += executable_match.group(2)

                if meta:
                    self._tree_meta_cache[path] = meta

                if path in tree_state:
                    # XXX What to do here?
                    # Should we ensure more important states are higher #?
                    # Or just list which ones shouldn't be overridden?
                    # This occurs because some files can be listed twice in 
                    # the status (conflicted and modified for eg)
                    if state > tree_state[path]:
                        tree_state[path] = state
                else:
                    tree_state[path] = state

    def _lookup_tree_cache(self, rootdir):
        # Get a list of all files in rootdir, as well as their status
        tree_state = {}
        # XXX This is odd. But if we create the cache on rootdir, the parent
        # assumes the cache contains everything, so we have to create it on
        # ./ instead.
        self._update_tree_state_cache('./', tree_state)
        return tree_state

    def update_file_state(self, path):
        tree_state = self._get_tree_cache(os.path.dirname(path))
        self._update_tree_state_cache(path, tree_state)

    def _get_dirsandfiles(self, directory, dirs, files):

        tree = self._get_tree_cache(directory)

        retfiles = []
        retdirs = []
        for name, path in files:
            state = tree.get(path, _vc.STATE_NORMAL)
            meta = self._tree_meta_cache.get(path, "")
            retfiles.append(_vc.File(path, name, state, options=meta))
        for name, path in dirs:
            # BZR can operate on directories.
            state = tree.get(path, _vc.STATE_NORMAL)
            meta = self._tree_meta_cache.get(path, "")
            retdirs.append(_vc.Dir(path, name, state, options=meta))
        for path, state in tree.items():
            # removed files are not in the filesystem, so must be added here
            if state in (_vc.STATE_REMOVED, _vc.STATE_MISSING):
                folder, name = os.path.split(path)
                if folder == directory:
                    retfiles.append(_vc.File(path, name, state))
        return retdirs, retfiles

    def get_path_for_repo_file(self, path, commit=None):
        if not path.startswith(self.root + os.path.sep):
            raise _vc.InvalidVCPath(self, path, "Path not in repository")

        path = path[len(self.root) + 1:]

        args = [self.CMD, "cat", path]
        if commit:
            args.append("-r%s" % commit)

        process = subprocess.Popen(args,
                                   cwd=self.root, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        vc_file = process.stdout

        # Error handling here involves doing nothing; in most cases, the only
        # sane response is to return an empty temp file.

        with tempfile.NamedTemporaryFile(prefix='meld-tmp', delete=False) as f:
            shutil.copyfileobj(vc_file, f)
        return f.name

    def get_path_for_conflict(self, path, conflict):
        if not path.startswith(self.root + os.path.sep):
            raise _vc.InvalidVCPath(self, path, "Path not in repository")

        # bzr paths are all temporary files
        return "%s%s" % (path, self.conflict_map[conflict]), False

    # Sensitivity button mappings.
    def update_actions_for_paths(self, path_states, actions):
        states = path_states.values()

        actions["VcCompare"] = bool(path_states)
        # TODO: We can't disable this for NORMAL, because folders don't
        # inherit any state from their children, but committing a folder with
        # modified children is expected behaviour.
        actions["VcCommit"] = all(s not in (
            _vc.STATE_NONE, _vc.STATE_IGNORED) for s in states)

        actions["VcUpdate"] = True
        # TODO: We can't do this; this shells out for each selection change...
        # actions["VcPush"] = bool(self.get_commits_to_push())
        actions["VcPush"] = True

        actions["VcAdd"] = all(s not in (
            _vc.STATE_NORMAL, _vc.STATE_REMOVED) for s in states)
        actions["VcResolved"] = all(s == _vc.STATE_CONFLICT for s in states)
        actions["VcRemove"] = (all(s not in (
            _vc.STATE_NONE, _vc.STATE_IGNORED,
            _vc.STATE_REMOVED) for s in states) and
            self.root not in path_states.keys())
        actions["VcRevert"] = all(s not in (
            _vc.STATE_NONE, _vc.STATE_NORMAL,
            _vc.STATE_IGNORED) for s in states)
