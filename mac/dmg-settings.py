# dmgbuild settings for Cellar's DMG. make-dmg.sh passes app, bg and icon with -D.
import os
app = defines["app"]
files = [app]
symlinks = {"Applications": "/Applications"}
icon = defines["icon"]
background = defines["bg"]
format = "UDZO"
window_rect = ((200, 160), (660, 460))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
icon_size = 112
text_size = 13
icon_locations = {os.path.basename(app): (180, 160), "Applications": (480, 160)}
hide_extensions = [os.path.basename(app)]
