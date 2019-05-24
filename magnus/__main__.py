#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Gio
import cairo, math, json, os, codecs, time, subprocess, sys
from functools import lru_cache

__VERSION__ = "1.0"


class Main(object):
    def __init__(self):
        self.zoomlevel = 2
        self.app = Gtk.Application.new("org.kryogenix.magnus", Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.app.connect("command-line", self.handle_commandline)
        self.resize_timeout = None
        self.window_metrics = None
        self.window_metrics_restored = False
        self.decorations_height = 0
        self.decorations_width = 0

    def handle_commandline(self, app, cmdline):
        if hasattr(self, "w"):
            # already started
            if "--about" in cmdline.get_arguments():
                self.show_about_dialog()
            return 0
        # First time startup
        self.start_everything_first_time()
        if "--about" in cmdline.get_arguments():
            self.show_about_dialog()
        return 0

    def start_everything_first_time(self, on_window_map=None):
        GLib.set_application_name("Magnus")

        # the window
        self.w = Gtk.ApplicationWindow.new(self.app)
        self.w.set_size_request(300, 300)
        self.w.set_title("Magnus")
        self.w.connect("destroy", Gtk.main_quit)
        self.w.connect("configure-event", self.read_window_size)
        self.w.connect("configure-event", self.window_configure)
        self.w.connect("size-allocate", self.read_window_decorations_size)
        devman = self.w.get_screen().get_display().get_device_manager()
        self.pointer = devman.get_client_pointer()

        # the headerbar
        head = Gtk.HeaderBar()
        head.set_show_close_button(True)
        head.props.title = "Magnus"
        self.w.set_titlebar(head)

        # the zoom chooser
        zoom = Gtk.ComboBoxText.new()
        self.zoom = zoom
        for i in range(2, 6):
            zoom.append(str(i), "{}×".format(i))
        zoom.set_active(0)
        zoom.connect("changed", self.set_zoom)
        head.pack_end(zoom)

        # the box that contains everything
        self.img = Gtk.Image()
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.add(self.img)
        self.w.add(scrolled_window)

        # and, go
        self.w.show_all()

        self.width = 0
        self.height = 0
        self.window_x = 0
        self.window_y = 0
        GLib.timeout_add(250, self.read_window_size)

        # and, poll
        GLib.timeout_add(250, self.poll)

        GLib.idle_add(self.load_config)

    def read_window_decorations_size(self, win, alloc):
        sz = self.w.get_size()
        self.decorations_width = alloc.width - sz.width
        self.decorations_height = alloc.height - sz.height

    def set_zoom(self, zoom):
        self.zoomlevel = int(zoom.get_active_text()[0])

    def read_window_size(self, *args):
        loc = self.w.get_size()
        self.width = loc.width
        self.height = loc.height

    def show_about_dialog(self, *args):
        about_dialog = Gtk.AboutDialog()
        about_dialog.set_artists(["Stuart Langridge"])
        about_dialog.set_authors(["Stuart Langridge"])
        about_dialog.set_version(__VERSION__)
        about_dialog.set_license_type(Gtk.License.MIT_X11)
        about_dialog.set_website("https://www.kryogenix.org/code/magnus")
        about_dialog.run()
        if about_dialog: about_dialog.destroy()

    @lru_cache()
    def makesquares(self, overall_width, overall_height, square_size, value_on, value_off):
        on_sq = list(value_on) * square_size
        off_sq = list(value_off) * square_size
        on_row = []
        off_row = []
        while len(on_row) < overall_width * len(value_on):
            on_row += on_sq
            on_row += off_sq
            off_row += off_sq
            off_row += on_sq
        on_row = on_row[:overall_width * len(value_on)]
        off_row = off_row[:overall_width * len(value_on)]

        on_sq_row = on_row * square_size
        off_sq_row = off_row * square_size

        overall = []
        count = 0
        while len(overall) < overall_width * overall_height * len(value_on):
            overall += on_sq_row
            overall += off_sq_row
            count += 2
        overall = overall[:overall_width * overall_height * len(value_on)]
        return overall

    @lru_cache()
    def get_white_pixbuf(self, width, height):
        square_size = 16
        light = (153, 153, 153, 255)
        dark = (102, 102, 102, 255)
        whole = self.makesquares(width, height, square_size, light, dark)
        arr = GLib.Bytes.new(whole)
        return GdkPixbuf.Pixbuf.new_from_bytes(arr, GdkPixbuf.Colorspace.RGB, True, 8, 
            width, height, width * len(light))

    def poll(self):
        display = Gdk.Display.get_default()
        (screen, x, y, modifier) = display.get_pointer()
        if (x > self.window_x and x <= (self.window_x + self.width + self.decorations_width) and
            y > self.window_y and y <= (self.window_y + self.height + self.decorations_height)):
            # pointer is over our window, so make it an empty pixbuf
            white = self.get_white_pixbuf(self.width, self.height)
            self.img.set_from_pixbuf(white)
        else:
            root = Gdk.get_default_root_window()
            scaled_width = self.width // self.zoomlevel
            scaled_height = self.height // self.zoomlevel
            scaled_xoff = scaled_width // 2
            scaled_yoff = scaled_height // 2
            screenshot = Gdk.pixbuf_get_from_window(root, x - scaled_xoff, y - scaled_yoff, scaled_width, scaled_height)
            scaled_pb = screenshot.scale_simple(self.width, self.height, GdkPixbuf.InterpType.NEAREST)
            self.img.set_from_pixbuf(scaled_pb)
        return True

    def window_configure(self, window, ev):
        if not self.window_metrics_restored: return False
        if self.resize_timeout:
            GLib.source_remove(self.resize_timeout)
        self.resize_timeout = GLib.timeout_add_seconds(1, self.save_window_metrics,
            {"x":ev.x, "y":ev.y, "w":ev.width, "h":ev.height})
        self.window_x = ev.x
        self.window_y = ev.y

    def save_window_metrics(self, props):
        scr = self.w.get_screen()
        sw = float(scr.get_width())
        sh = float(scr.get_height())
        # We save window dimensions as fractions of the screen dimensions, to cope with screen
        # resolution changes while we weren't running
        self.window_metrics = {
            "ww": props["w"] / sw,
            "wh": props["h"] / sh,
            "wx": props["x"] / sw,
            "wy": props["y"] / sh
        }
        self.serialise()

    def restore_window_metrics(self, metrics):
        scr = self.w.get_screen()
        sw = float(scr.get_width())
        sh = float(scr.get_height())
        self.w.set_size_request(int(sw * metrics["ww"]), int(sh * metrics["wh"]))
        self.w.move(int(sw * metrics["wx"]), int(sh * metrics["wy"]))

    def get_cache_file(self):
        return os.path.join(GLib.get_user_cache_dir(), "magnus.json")

    def serialise(self, *args, **kwargs):
        # yeah, yeah, supposed to use Gio's async file stuff here. But it was writing
        # corrupted files, and I have no idea why; probably the Python var containing
        # the data was going out of scope or something. Anyway, we're only storing
        # a small JSON file, so life's too short to hammer on this; we'll write with
        # Python and take the hit.
        fp = codecs.open(self.get_cache_file(), encoding="utf8", mode="w")
        data = {"zoom": self.zoomlevel}
        if self.window_metrics:
            data["metrics"] = self.window_metrics
        json.dump(data, fp, indent=2)
        fp.close()

    def load_config(self):
        f = Gio.File.new_for_path(self.get_cache_file())
        f.load_contents_async(None, self.finish_loading_history)

    def finish_loading_history(self, f, res):
        try:
            try:
                success, contents, _ = f.load_contents_finish(res)
            except GLib.Error as e:
                print("couldn't restore settings (error: %s), so assuming they're blank" % (e,))
                contents = "{}" # fake contents

            data = json.loads(contents)
            zl = data.get("zoom")
            if zl:
                idx = 0
                for row in self.zoom.get_model():
                    text, lid = list(row)
                    if lid == str(zl):
                        self.zoom.set_active(idx)
                        self.zoomlevel = zl
                    idx += 1
            metrics = data.get("metrics")
            if metrics:
                self.restore_window_metrics(metrics)
            self.window_metrics_restored = True

        except:
            #print "Failed to restore data"
            raise



def main():
    m = Main()
    m.app.run(sys.argv)

if __name__ == "__main__": main()
