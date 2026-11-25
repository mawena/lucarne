"""Application GTK de Lucarne (une seule fenêtre ; relancer Lucarne la remet au premier plan)."""
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Adw, Gio, Gst, Gtk  # noqa: E402

from . import APP_ID, __version__  # noqa: E402


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.fenetre = None
        for nom, rappel, touches in (("about", self._a_propos, []), ("quit", self._quitter, ["<Control>q"])):
            action = Gio.SimpleAction.new(nom, None)
            action.connect("activate", rappel)
            self.add_action(action)
            if touches:
                self.set_accels_for_action(f"app.{nom}", touches)

    def do_activate(self):
        if self.fenetre is None:
            from .fenetre import Fenetre
            self.fenetre = Fenetre(self)
        self.fenetre.present()

    def _a_propos(self, *_):
        proprietes = dict(
            application_name="Lucarne", application_icon=APP_ID, version=__version__,
            developer_name="mawena", license_type=Gtk.License.MIT_X11,
            website="https://github.com/mawena/Lucarne",
            issue_url="https://github.com/mawena/Lucarne/issues",
            comments="L'image d'une carte de capture avec le moins de retard possible, et son son où tu veux.",
        )
        if hasattr(Adw, "AboutDialog"):
            Adw.AboutDialog(**proprietes).present(self.fenetre)
        else:
            Adw.AboutWindow(transient_for=self.fenetre, **proprietes).present()

    def _quitter(self, *_):
        if self.fenetre is not None:
            self.fenetre.close()
        self.quit()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if "--version" in argv[1:]:
        print(f"lucarne {__version__}")
        return 0
    Gst.init(None)
    return Application().run(argv[:1])
