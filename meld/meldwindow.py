# Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>
# Copyright (C) 2010-2013 Kai Willadsen <kai.willadsen@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

from . import dirdiff
from . import filediff
from . import filemerge
from . import melddoc
from . import newdifftab
from . import recent
from . import task
from . import vcview
from .ui import gnomeglade
from .ui import notebooklabel

from .util.compat import string_types
from meld.conf import _
from meld.recent import recent_comparisons
from meld.settings import interface_settings, settings


class MeldWindow(gnomeglade.Component):

    def __init__(self):
        gnomeglade.Component.__init__(self, "meldapp.ui", "meldapp")
        self.widget.set_name("meldapp")

        actions = (
            ("FileMenu", None, _("_File")),
            ("New", Gtk.STOCK_NEW, _("_New Comparison..."), "<control>N",
                _("Start a new comparison"),
                self.on_menu_file_new_activate),
            ("Save", Gtk.STOCK_SAVE, None, None,
                _("Save the current file"),
                self.on_menu_save_activate),
            ("SaveAs", Gtk.STOCK_SAVE_AS, _("Save As..."), "<control><shift>S",
                _("Save the current file with a different name"),
                self.on_menu_save_as_activate),
            ("Close", Gtk.STOCK_CLOSE, None, None,
                _("Close the current file"),
                self.on_menu_close_activate),

            ("EditMenu", None, _("_Edit")),
            ("Undo", Gtk.STOCK_UNDO, None, "<control>Z",
                _("Undo the last action"),
                self.on_menu_undo_activate),
            ("Redo", Gtk.STOCK_REDO, None, "<control><shift>Z",
                _("Redo the last undone action"),
                self.on_menu_redo_activate),
            ("Cut", Gtk.STOCK_CUT, None, None, _("Cut the selection"),
                self.on_menu_cut_activate),
            ("Copy", Gtk.STOCK_COPY, None, None, _("Copy the selection"),
                self.on_menu_copy_activate),
            ("Paste", Gtk.STOCK_PASTE, None, None, _("Paste the clipboard"),
                self.on_menu_paste_activate),
            ("Find", Gtk.STOCK_FIND, _("Find..."), None, _("Search for text"),
                self.on_menu_find_activate),
            ("FindNext", None, _("Find Ne_xt"), "<control>G",
                _("Search forwards for the same text"),
                self.on_menu_find_next_activate),
            ("FindPrevious", None, _("Find _Previous"), "<control><shift>G",
                _("Search backwards for the same text"),
                self.on_menu_find_previous_activate),
            ("Replace", Gtk.STOCK_FIND_AND_REPLACE,
                _("_Replace..."), "<control>H",
                _("Find and replace text"),
                self.on_menu_replace_activate),

            ("ChangesMenu", None, _("_Changes")),
            ("NextChange", Gtk.STOCK_GO_DOWN, _("Next Change"), "<Alt>Down",
                _("Go to the next change"),
                self.on_menu_edit_down_activate),
            ("PrevChange", Gtk.STOCK_GO_UP, _("Previous Change"), "<Alt>Up",
                _("Go to the previous change"),
                self.on_menu_edit_up_activate),
            ("OpenExternal", None, _("Open Externally"), None,
                _("Open selected file or directory in the default external "
                  "application"),
                self.on_open_external),

            ("ViewMenu", None, _("_View")),
            ("FileStatus", None, _("File Status")),
            ("VcStatus", None, _("Version Status")),
            ("FileFilters", None, _("File Filters")),
            ("Stop", Gtk.STOCK_STOP, None, "Escape",
                _("Stop the current action"),
                self.on_toolbar_stop_clicked),
            ("Refresh", Gtk.STOCK_REFRESH, None, "<control>R",
                _("Refresh the view"),
                self.on_menu_refresh_activate),

            ("TabMenu", None, _("_Tabs")),
            ("PrevTab",   None, _("_Previous Tab"), "<Ctrl><Alt>Page_Up",
                _("Activate previous tab"),
                self.on_prev_tab),
            ("NextTab",   None, _("_Next Tab"), "<Ctrl><Alt>Page_Down",
                _("Activate next tab"),
                self.on_next_tab),
            ("MoveTabPrev", None,
                _("Move Tab _Left"), "<Ctrl><Alt><Shift>Page_Up",
                _("Move current tab to left"),
                self.on_move_tab_prev),
            ("MoveTabNext", None,
                _("Move Tab _Right"), "<Ctrl><Alt><Shift>Page_Down",
                _("Move current tab to right"),
                self.on_move_tab_next),
        )
        toggleactions = (
            ("Fullscreen", None, _("Fullscreen"), "F11",
                _("View the comparison in fullscreen"),
                self.on_action_fullscreen_toggled, False),
            ("ToolbarVisible", None, _("_Toolbar"), None,
                _("Show or hide the toolbar"),
                None, True),
        )
        ui_file = gnomeglade.ui_file("meldapp-ui.xml")
        self.actiongroup = Gtk.ActionGroup(name='MainActions')
        self.actiongroup.set_translation_domain("meld")
        self.actiongroup.add_actions(actions)
        self.actiongroup.add_toggle_actions(toggleactions)

        recent_action = Gtk.RecentAction(name="Recent",  label=_("Open Recent"),
                                         tooltip=_("Open recent files"), stock_id=None)
        recent_action.set_show_private(True)
        recent_action.set_filter(recent_comparisons.recent_filter)
        recent_action.set_sort_type(Gtk.RecentSortType.MRU)
        recent_action.connect("item-activated", self.on_action_recent)
        self.actiongroup.add_action(recent_action)

        self.ui = Gtk.UIManager()
        self.ui.insert_action_group(self.actiongroup, 0)
        self.ui.add_ui_from_file(ui_file)
        self.tab_switch_actiongroup = None
        self.tab_switch_merge_id = None

        for menuitem in ("Save", "Undo"):
            self.actiongroup.get_action(menuitem).props.is_important = True
        self.widget.add_accel_group(self.ui.get_accel_group())
        self.menubar = self.ui.get_widget('/Menubar')
        self.toolbar = self.ui.get_widget('/Toolbar')
        self.toolbar.get_style_context().add_class(
            Gtk.STYLE_CLASS_PRIMARY_TOOLBAR)

        settings.bind('toolbar-visible',
                      self.actiongroup.get_action('ToolbarVisible'), 'active',
                      Gio.SettingsBindFlags.DEFAULT)
        settings.bind('toolbar-visible', self.toolbar, 'visible',
                      Gio.SettingsBindFlags.DEFAULT)
        interface_settings.bind('toolbar-style', self.toolbar, 'toolbar-style',
                                Gio.SettingsBindFlags.DEFAULT)

        # Add alternate keybindings for Prev/Next Change
        accels = self.ui.get_accel_group()
        (keyval, mask) = Gtk.accelerator_parse("<Ctrl>D")
        accels.connect(keyval, mask, 0, self.on_menu_edit_down_activate)
        (keyval, mask) = Gtk.accelerator_parse("<Ctrl>E")
        accels.connect(keyval, mask, 0, self.on_menu_edit_up_activate)
        (keyval, mask) = Gtk.accelerator_parse("F5")
        accels.connect(keyval, mask, 0, self.on_menu_refresh_activate)

        # Initialise sensitivity for important actions
        self.actiongroup.get_action("Stop").set_sensitive(False)
        self._update_page_action_sensitivity()

        self.appvbox.pack_start(self.menubar, False, True, 0)
        self.toolbar_holder.pack_start(self.toolbar, True, True, 0)

        # Double toolbars to work around UIManager integration issues
        self.secondary_toolbar = Gtk.Toolbar()
        self.secondary_toolbar.get_style_context().add_class(
            Gtk.STYLE_CLASS_PRIMARY_TOOLBAR)
        self.toolbar_holder.pack_end(self.secondary_toolbar, False, True, 0)

        toolbutton = Gtk.ToolItem()
        self.spinner = Gtk.Spinner()
        toolbutton.add(self.spinner)
        self.secondary_toolbar.insert(toolbutton, -1)
        # Set a minimum size because the spinner requests nothing
        self.secondary_toolbar.set_size_request(30, -1)
        self.secondary_toolbar.show_all()

        self.widget.drag_dest_set(
            Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT |
            Gtk.DestDefaults.DROP,
            None, Gdk.DragAction.COPY)
        self.widget.drag_dest_add_uri_targets()
        self.widget.connect("drag_data_received",
                            self.on_widget_drag_data_received)
        self.idle_hooked = 0
        self.scheduler = task.LifoScheduler()
        self.scheduler.connect("runnable", self.on_scheduler_runnable)
        window_size = settings.get_value('window-size')
        self.widget.set_default_size(window_size[0], window_size[1])
        self.ui.ensure_update()
        self.diff_handler = None
        self.undo_handlers = tuple()
        self.widget.connect('focus_in_event', self.on_focus_change)
        self.widget.connect('focus_out_event', self.on_focus_change)

    def on_focus_change(self, widget, event, callback_data=None):
        for idx in range(self.notebook.get_n_pages()):
            w = self.notebook.get_nth_page(idx)
            if hasattr(w.pyobject, 'on_focus_change'):
                w.pyobject.on_focus_change()
        # Let the rest of the stack know about this event
        return False

    def on_widget_drag_data_received(self, wid, context, x, y, selection_data,
                                     info, time):
        if len(selection_data.get_uris()) != 0:
            paths = []
            for uri in selection_data.get_uris():
                paths.append(Gio.File.new_for_uri(uri).get_path())
            self.open_paths(paths)
            return True

    def on_idle(self):
        ret = self.scheduler.iteration()
        if ret and isinstance(ret, string_types):
            self.spinner.set_tooltip_text(ret)

        pending = self.scheduler.tasks_pending()
        if not pending:
            self.spinner.stop()
            self.spinner.hide()
            self.spinner.set_tooltip_text("")
            self.idle_hooked = None
            self.actiongroup.get_action("Stop").set_sensitive(False)
        return pending

    def on_scheduler_runnable(self, sched):
        if not self.idle_hooked:
            self.spinner.show()
            self.spinner.start()
            self.actiongroup.get_action("Stop").set_sensitive(True)
            self.idle_hooked = GLib.idle_add(self.on_idle)

    def on_delete_event(self, *extra):
        # Delete pages from right-to-left.  This ensures that if a version
        # control page is open in the far left page, it will be closed last.
        for c in reversed(self.notebook.get_children()):
            page = c.pyobject
            self.notebook.set_current_page(self.notebook.page_num(page.widget))
            response = self.try_remove_page(page, appquit=1)
            if response == Gtk.ResponseType.CANCEL:
                return True

    def has_pages(self):
        return self.notebook.get_n_pages() > 0

    def _update_page_action_sensitivity(self):
        current_page = self.notebook.get_current_page()
        have_prev_tab = current_page > 0
        have_next_tab = current_page < self.notebook.get_n_pages() - 1
        self.actiongroup.get_action("PrevTab").set_sensitive(have_prev_tab)
        self.actiongroup.get_action("NextTab").set_sensitive(have_next_tab)
        self.actiongroup.get_action("MoveTabPrev").set_sensitive(have_prev_tab)
        self.actiongroup.get_action("MoveTabNext").set_sensitive(have_next_tab)

        if current_page != -1:
            page = self.notebook.get_nth_page(current_page).pyobject
        else:
            page = None

        self.actiongroup.get_action("Close").set_sensitive(bool(page))
        if not isinstance(page, melddoc.MeldDoc):
            for action in ("PrevChange", "NextChange", "Cut", "Copy", "Paste",
                           "Find", "FindNext", "FindPrevious", "Replace",
                           "Refresh"):
                self.actiongroup.get_action(action).set_sensitive(False)
        else:
            for action in ("Find", "Refresh"):
                self.actiongroup.get_action(action).set_sensitive(True)
            is_filediff = isinstance(page, filediff.FileDiff)
            for action in ("Cut", "Copy", "Paste", "FindNext", "FindPrevious",
                           "Replace"):
                self.actiongroup.get_action(action).set_sensitive(is_filediff)

    def on_switch_page(self, notebook, page, which):
        oldidx = notebook.get_current_page()
        if oldidx >= 0:
            olddoc = notebook.get_nth_page(oldidx).pyobject
            if self.diff_handler is not None:
                olddoc.disconnect(self.diff_handler)
            olddoc.on_container_switch_out_event(self.ui)
            if self.undo_handlers:
                undoseq = olddoc.undosequence
                for handler in self.undo_handlers:
                    undoseq.disconnect(handler)
                self.undo_handlers = tuple()

        newdoc = notebook.get_nth_page(which).pyobject
        try:
            undoseq = newdoc.undosequence
            can_undo = undoseq.can_undo()
            can_redo = undoseq.can_redo()
            undo_handler = undoseq.connect("can-undo", self.on_can_undo)
            redo_handler = undoseq.connect("can-redo", self.on_can_redo)
            self.undo_handlers = (undo_handler, redo_handler)
        except AttributeError:
            can_undo, can_redo = False, False
        self.actiongroup.get_action("Undo").set_sensitive(can_undo)
        self.actiongroup.get_action("Redo").set_sensitive(can_redo)

        # FileDiff handles save sensitivity; it makes no sense for other modes
        if not isinstance(newdoc, filediff.FileDiff):
            self.actiongroup.get_action("Save").set_sensitive(False)
            self.actiongroup.get_action("SaveAs").set_sensitive(False)
        else:
            self.actiongroup.get_action("SaveAs").set_sensitive(True)

        nbl = self.notebook.get_tab_label(newdoc.widget)
        self.widget.set_title(nbl.get_label_text() + " - Meld")
        newdoc.on_container_switch_in_event(self.ui)
        if isinstance(newdoc, melddoc.MeldDoc):
            self.diff_handler = newdoc.connect("next-diff-changed",
                                               self.on_next_diff_changed)
        else:
            self.diff_handler = None
        if hasattr(newdoc, 'scheduler'):
            self.scheduler.add_task(newdoc.scheduler)

    def after_switch_page(self, notebook, page, which):
        self._update_page_action_sensitivity()
        actiongroup = self.tab_switch_actiongroup
        if actiongroup:
            action_name = "SwitchTab%d" % which
            actiongroup.get_action(action_name).set_active(True)

    def after_page_reordered(self, notebook, page, page_num):
        self._update_page_action_sensitivity()

    def on_notebook_label_changed(self, component, text, tooltip):
        page = component.widget
        nbl = self.notebook.get_tab_label(page)
        nbl.set_label_text(text)
        nbl.set_tooltip_text(tooltip)

        # Only update the window title if the current page is active
        if self.notebook.get_current_page() == self.notebook.page_num(page):
            self.widget.set_title(text + " - Meld")
        if isinstance(text, unicode):
            text = text.encode('utf8')
        self.notebook.child_set_property(page, "menu-label", text)

        actiongroup = self.tab_switch_actiongroup
        if actiongroup:
            idx = self.notebook.page_num(page)
            action_name = "SwitchTab%d" % idx
            actiongroup.get_action(action_name).set_label(text)

    def on_can_undo(self, undosequence, can):
        self.actiongroup.get_action("Undo").set_sensitive(can)

    def on_can_redo(self, undosequence, can):
        self.actiongroup.get_action("Redo").set_sensitive(can)

    def on_next_diff_changed(self, doc, have_prev, have_next):
        self.actiongroup.get_action("PrevChange").set_sensitive(have_prev)
        self.actiongroup.get_action("NextChange").set_sensitive(have_next)

    def on_configure_event(self, window, event):
        state = event.window.get_state()
        nosave = Gdk.WindowState.FULLSCREEN | Gdk.WindowState.MAXIMIZED
        if not (state & nosave):
            variant = GLib.Variant('(ii)', (event.width, event.height))
            settings.set_value('window-size', variant)

    def on_menu_file_new_activate(self, menuitem):
        self.append_new_comparison()

    def on_menu_save_activate(self, menuitem):
        self.current_doc().save()

    def on_menu_save_as_activate(self, menuitem):
        self.current_doc().save_as()

    def on_action_recent(self, action):
        uri = action.get_current_uri()
        if not uri:
            return
        try:
            self.append_recent(uri)
        except (IOError, ValueError):
            # FIXME: Need error handling, but no sensible display location
            pass

    def on_menu_close_activate(self, *extra):
        i = self.notebook.get_current_page()
        if i >= 0:
            page = self.notebook.get_nth_page(i).pyobject
            self.try_remove_page(page)

    def on_menu_undo_activate(self, *extra):
        self.current_doc().on_undo_activate()

    def on_menu_redo_activate(self, *extra):
        self.current_doc().on_redo_activate()

    def on_menu_refresh_activate(self, *extra):
        self.current_doc().on_refresh_activate()

    def on_menu_find_activate(self, *extra):
        self.current_doc().on_find_activate()

    def on_menu_find_next_activate(self, *extra):
        self.current_doc().on_find_next_activate()

    def on_menu_find_previous_activate(self, *extra):
        self.current_doc().on_find_previous_activate()

    def on_menu_replace_activate(self, *extra):
        self.current_doc().on_replace_activate()

    def on_menu_copy_activate(self, *extra):
        widget = self.widget.get_focus()
        if isinstance(widget, Gtk.Editable):
            widget.copy_clipboard()
        elif isinstance(widget, Gtk.TextView):
            widget.emit("copy-clipboard")

    def on_menu_cut_activate(self, *extra):
        widget = self.widget.get_focus()
        if isinstance(widget, Gtk.Editable):
            widget.cut_clipboard()
        elif isinstance(widget, Gtk.TextView):
            widget.emit("cut-clipboard")

    def on_menu_paste_activate(self, *extra):
        widget = self.widget.get_focus()
        if isinstance(widget, Gtk.Editable):
            widget.paste_clipboard()
        elif isinstance(widget, Gtk.TextView):
            widget.emit("paste-clipboard")

    def on_action_fullscreen_toggled(self, widget):
        window_state = self.widget.get_window().get_state()
        is_full = window_state & Gdk.WindowState.FULLSCREEN
        if widget.get_active() and not is_full:
            self.widget.fullscreen()
        elif is_full:
            self.widget.unfullscreen()

    def on_menu_edit_down_activate(self, *args):
        self.current_doc().next_diff(Gdk.ScrollDirection.DOWN)

    def on_menu_edit_up_activate(self, *args):
        self.current_doc().next_diff(Gdk.ScrollDirection.UP)

    def on_open_external(self, *args):
        self.current_doc().open_external()

    def on_toolbar_stop_clicked(self, *args):
        self.current_doc().stop()

    def on_prev_tab(self, *args):
        self.notebook.prev_page()

    def on_next_tab(self, *args):
        self.notebook.next_page()

    def on_move_tab_prev(self, *args):
        page_num = self.notebook.get_current_page()
        child = self.notebook.get_nth_page(page_num)
        page_num = page_num - 1 if page_num > 0 else 0
        self.notebook.reorder_child(child, page_num)

    def on_move_tab_next(self, *args):
        page_num = self.notebook.get_current_page()
        child = self.notebook.get_nth_page(page_num)
        self.notebook.reorder_child(child, page_num + 1)

    def _update_notebook_menu(self, *args):
        if self.tab_switch_merge_id:
            self.ui.remove_ui(self.tab_switch_merge_id)
            self.ui.remove_action_group(self.tab_switch_actiongroup)

        self.tab_switch_merge_id = self.ui.new_merge_id()
        self.tab_switch_actiongroup = Gtk.ActionGroup(name="TabSwitchActions")
        self.ui.insert_action_group(self.tab_switch_actiongroup)
        group = None
        current_page = self.notebook.get_current_page()
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            label = self.notebook.get_menu_label_text(page) or ""
            name = "SwitchTab%d" % i
            tooltip = _("Switch to this tab")
            action = Gtk.RadioAction(name=name, label=label, tooltip=tooltip, stock_id=None, value=i)
            action.join_group(group)
            group = action
            action.set_active(current_page == i)

            def current_tab_changed_cb(action, current):
                if action == current:
                    self.notebook.set_current_page(action.get_current_value())
            action.connect("changed", current_tab_changed_cb)
            if i < 10:
                accel = "<Alt>%d" % ((i + 1) % 10)
            else:
                accel = None
            self.tab_switch_actiongroup.add_action_with_accel(action, accel)
            self.ui.add_ui(self.tab_switch_merge_id,
                           "/Menubar/TabMenu/TabPlaceholder",
                           name, name, Gtk.UIManagerItemType.MENUITEM, False)

    def try_remove_page(self, page, appquit=0):
        "See if a page will allow itself to be removed"
        response = page.on_delete_event(appquit)
        if response != Gtk.ResponseType.CANCEL:
            if hasattr(page, 'scheduler'):
                self.scheduler.remove_scheduler(page.scheduler)
            page_num = self.notebook.page_num(page.widget)
            assert page_num >= 0

            # If the page we're removing is the current page, we need to
            # disconnect and clear undo handlers, and trigger a switch out
            if self.notebook.get_current_page() == page_num:
                if self.diff_handler is not None:
                    page.disconnect(self.diff_handler)
                if self.undo_handlers:
                    for handler in self.undo_handlers:
                        page.undosequence.disconnect(handler)
                self.undo_handlers = tuple()
                page.on_container_switch_out_event(self.ui)

            self.notebook.remove_page(page_num)
            if self.notebook.get_n_pages() == 0:
                self.widget.set_title("Meld")
                self._update_page_action_sensitivity()
        return response

    def on_file_changed(self, srcpage, filename):
        for c in self.notebook.get_children():
            page = c.pyobject
            if page != srcpage:
                page.on_file_changed(filename)

    def _append_page(self, page, icon):
        nbl = notebooklabel.NotebookLabel(icon, "",
                                          lambda b: self.try_remove_page(page))
        self.notebook.append_page(page.widget, nbl)

        # Change focus to the newly created page only if the user is on a
        # DirDiff or VcView page, or if it's a new tab page. This prevents
        # cycling through X pages when X diffs are initiated.
        if isinstance(self.current_doc(), dirdiff.DirDiff) or \
           isinstance(self.current_doc(), vcview.VcView) or \
           isinstance(page, newdifftab.NewDiffTab):
            self.notebook.set_current_page(self.notebook.page_num(page.widget))

        if hasattr(page, 'scheduler'):
            self.scheduler.add_scheduler(page.scheduler)
        if isinstance(page, melddoc.MeldDoc):
            page.connect("label-changed", self.on_notebook_label_changed)
            page.connect("file-changed", self.on_file_changed)
            page.connect("create-diff", lambda obj, arg, kwargs:
                         self.append_diff(arg, **kwargs))

        self.notebook.set_tab_reorderable(page.widget, True)

    def append_new_comparison(self):
        doc = newdifftab.NewDiffTab(self)
        self._append_page(doc, "document-new")
        self.on_notebook_label_changed(doc, _("New comparison"), None)

        def diff_created_cb(doc, newdoc):
            self.try_remove_page(doc)
            idx = self.notebook.page_num(newdoc.widget)
            self.notebook.set_current_page(idx)

        doc.connect("diff-created", diff_created_cb)
        return doc

    def append_dirdiff(self, dirs, auto_compare=False):
        assert len(dirs) in (1, 2, 3)
        doc = dirdiff.DirDiff(len(dirs))
        self._append_page(doc, "folder")
        doc.set_locations(dirs)
        # FIXME: This doesn't work, as dirdiff behaves differently to vcview
        if auto_compare:
            doc.on_button_diff_clicked(None)
        return doc

    def append_filediff(self, files,  merge_output=None, meta=None):
        assert len(files) in (1, 2, 3)
        doc = filediff.FileDiff(len(files))
        self._append_page(doc, "text-x-generic")
        doc.set_files(files)
        if merge_output is not None:
            doc.set_merge_output_file(merge_output)
        if meta is not None:
            doc.set_meta(meta)
        return doc

    def append_filemerge(self, files, merge_output=None):
        assert len(files) == 3
        doc = filemerge.FileMerge(len(files))
        self._append_page(doc, "text-x-generic")
        doc.set_files(files)
        if merge_output is not None:
            doc.set_merge_output_file(merge_output)
        return doc

    def append_diff(self, paths, auto_compare=False, auto_merge=False,
                    merge_output=None, meta=None):
        dirslist = [p for p in paths if os.path.isdir(p)]
        fileslist = [p for p in paths if os.path.isfile(p)]
        if dirslist and fileslist:
            raise ValueError(
                _("Cannot compare a mixture of files and directories"))
        elif dirslist:
            return self.append_dirdiff(paths, auto_compare)
        elif auto_merge:
            return self.append_filemerge(paths, merge_output=merge_output)
        else:
            return self.append_filediff(
                paths, merge_output=merge_output, meta=meta)

    def append_vcview(self, location, auto_compare=False):
        doc = vcview.VcView()
        self._append_page(doc, "meld-version-control")
        location = location[0] if isinstance(location, list) else location
        doc.set_location(location)
        if auto_compare:
            doc.on_button_diff_clicked(None)
        return doc

    def append_recent(self, uri):
        comparison_type, files, flags = recent_comparisons.read(uri)
        if comparison_type == recent.TYPE_MERGE:
            tab = self.append_filemerge(files)
        elif comparison_type == recent.TYPE_FOLDER:
            tab = self.append_dirdiff(files)
        elif comparison_type == recent.TYPE_VC:
            # Files should be a single-element iterable
            tab = self.append_vcview(files[0])
        else:  # comparison_type == recent.TYPE_FILE:
            tab = self.append_filediff(files)
        self.notebook.set_current_page(self.notebook.page_num(tab.widget))
        recent_comparisons.add(tab)
        return tab

    def _single_file_open(self, path):
        doc = vcview.VcView()

        def cleanup():
            self.scheduler.remove_scheduler(doc.scheduler)
        self.scheduler.add_task(cleanup)
        self.scheduler.add_scheduler(doc.scheduler)
        path = os.path.abspath(path)
        doc.set_location(path)
        doc.connect("create-diff", lambda obj, arg, kwargs:
                    self.append_diff(arg, **kwargs))
        doc.run_diff(path)

    def open_paths(self, paths, auto_compare=False, auto_merge=False,
                   focus=False):
        tab = None
        if len(paths) == 1:
            a = paths[0]
            if os.path.isfile(a):
                self._single_file_open(a)
            else:
                tab = self.append_vcview(a, auto_compare)

        elif len(paths) in (2, 3):
            tab = self.append_diff(
                paths, auto_compare=auto_compare, auto_merge=auto_merge)
        if tab:
            recent_comparisons.add(tab)
            if focus:
                self.notebook.set_current_page(
                    self.notebook.page_num(tab.widget))

        return tab

    def current_doc(self):
        "Get the current doc or a dummy object if there is no current"
        index = self.notebook.get_current_page()
        if index >= 0:
            page = self.notebook.get_nth_page(index).pyobject
            if isinstance(page, melddoc.MeldDoc):
                return page

        class DummyDoc(object):
            def __getattr__(self, a):
                return lambda *x: None
        return DummyDoc()
