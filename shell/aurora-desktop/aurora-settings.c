/*
 * aurora-settings — AuroraOS's own System Settings app.
 *
 * A small native GTK3 app (regular xdg-toplevel window, not a layer surface) in
 * the Aurora "daybreak" identity. Sidebar + stack of pages: About, Display,
 * Sound, Network, Power. Reads live system state from /proc and sysfs, controls
 * volume via amixer, and drives session power actions via systemctl. Deliberately
 * dependency-light so it always launches on the base system.
 */
#include <gtk/gtk.h>
#include <stdio.h>
#include <string.h>
#include <sys/utsname.h>
#include <unistd.h>

/* ---- tiny helpers ---- */
static char *slurp(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return NULL;
    char *buf = NULL; size_t n = 0;
    ssize_t r = getline(&buf, &n, f);
    fclose(f);
    if (r <= 0) { free(buf); return NULL; }
    while (r > 0 && (buf[r-1] == '\n' || buf[r-1] == '\r')) buf[--r] = 0;
    return buf;
}
static void run_async(const char *cmd) {
    char **argv = NULL;
    if (g_shell_parse_argv(cmd, NULL, &argv, NULL)) {
        g_spawn_async(NULL, argv, NULL,
                      G_SPAWN_SEARCH_PATH | G_SPAWN_STDOUT_TO_DEV_NULL |
                      G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL, NULL, NULL);
        g_strfreev(argv);
    }
}

/* ---- row/section builders ---- */
static GtkWidget *card(void) {
    GtkWidget *b = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_style_context_add_class(gtk_widget_get_style_context(b), "card");
    return b;
}
static void add_kv(GtkWidget *card, const char *k, const char *v) {
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_style_context_add_class(gtk_widget_get_style_context(row), "row");
    GtkWidget *kl = gtk_label_new(k);
    gtk_widget_set_halign(kl, GTK_ALIGN_START);
    gtk_style_context_add_class(gtk_widget_get_style_context(kl), "k");
    GtkWidget *vl = gtk_label_new(v ? v : "—");
    gtk_widget_set_halign(vl, GTK_ALIGN_END);
    gtk_widget_set_hexpand(vl, TRUE);
    gtk_label_set_ellipsize(GTK_LABEL(vl), PANGO_ELLIPSIZE_END);
    gtk_style_context_add_class(gtk_widget_get_style_context(vl), "v");
    gtk_box_pack_start(GTK_BOX(row), kl, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(row), vl, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(card), row, FALSE, FALSE, 0);
}
static GtkWidget *page_scroll(GtkWidget *inner) {
    gtk_widget_set_margin_start(inner, 26); gtk_widget_set_margin_end(inner, 26);
    gtk_widget_set_margin_top(inner, 24);   gtk_widget_set_margin_bottom(inner, 24);
    GtkWidget *sc = gtk_scrolled_window_new(NULL, NULL);
    gtk_container_add(GTK_CONTAINER(sc), inner);
    return sc;
}
static GtkWidget *page_title(const char *t) {
    GtkWidget *l = gtk_label_new(t);
    gtk_widget_set_halign(l, GTK_ALIGN_START);
    gtk_style_context_add_class(gtk_widget_get_style_context(l), "ptitle");
    return l;
}

/* ---- About ---- */
static GtkWidget *build_about(void) {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    GtkWidget *hero = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    gtk_style_context_add_class(gtk_widget_get_style_context(hero), "hero");
    GtkWidget *mark = gtk_label_new(NULL);
    gtk_label_set_markup(GTK_LABEL(mark),
        "<span foreground='#34e0c8' size='xx-large'>◗</span>");
    GtkWidget *name = gtk_label_new("AuroraOS");
    gtk_style_context_add_class(gtk_widget_get_style_context(name), "hname");
    GtkWidget *ver = gtk_label_new("1.0 — Daybreak");
    gtk_style_context_add_class(gtk_widget_get_style_context(ver), "hver");
    gtk_box_pack_start(GTK_BOX(hero), mark, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(hero), name, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(hero), ver, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), hero, FALSE, FALSE, 0);

    GtkWidget *c = card();
    struct utsname un; uname(&un);
    add_kv(c, "Kernel", un.release);
    char *host = slurp("/etc/hostname"); add_kv(c, "Device name", host ? host : "aurora"); g_free(host);
    long cores = sysconf(_SC_NPROCESSORS_ONLN);
    char cbuf[32]; snprintf(cbuf, sizeof cbuf, "%ld", cores); add_kv(c, "Processors", cbuf);
    /* total memory from /proc/meminfo */
    FILE *m = fopen("/proc/meminfo", "r"); char line[128]; char mem[32] = "—";
    if (m) { while (fgets(line, sizeof line, m)) { long kb;
        if (sscanf(line, "MemTotal: %ld kB", &kb) == 1) { snprintf(mem, sizeof mem, "%.1f GiB", kb/1048576.0); break; } }
        fclose(m); }
    add_kv(c, "Memory", mem);
    add_kv(c, "Graphics", "VMSVGA · vmwgfx (software)");
    add_kv(c, "Desktop", "Aurora shell · labwc/Wayland");
    gtk_box_pack_start(GTK_BOX(v), c, FALSE, FALSE, 0);

    GtkWidget *note = gtk_label_new("A private, on-device AI desktop built from Linux From Scratch.");
    gtk_widget_set_halign(note, GTK_ALIGN_START);
    gtk_label_set_line_wrap(GTK_LABEL(note), TRUE);
    gtk_style_context_add_class(gtk_widget_get_style_context(note), "note");
    gtk_box_pack_start(GTK_BOX(v), note, FALSE, FALSE, 0);
    return page_scroll(v);
}

/* ---- Display ---- */
static GtkWidget *build_display(void) {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    gtk_box_pack_start(GTK_BOX(v), page_title("Display"), FALSE, FALSE, 0);
    GtkWidget *c = card();
    add_kv(c, "Resize", "Follows the window automatically");
    add_kv(c, "Guest Additions", "Active");
    gtk_box_pack_start(GTK_BOX(v), c, FALSE, FALSE, 0);
    GtkWidget *note = gtk_label_new("The desktop resolution tracks the VirtualBox window. "
        "Drag the window edge and the desktop follows.");
    gtk_widget_set_halign(note, GTK_ALIGN_START);
    gtk_label_set_line_wrap(GTK_LABEL(note), TRUE);
    gtk_style_context_add_class(gtk_widget_get_style_context(note), "note");
    gtk_box_pack_start(GTK_BOX(v), note, FALSE, FALSE, 0);
    return page_scroll(v);
}

/* ---- Sound ---- */
static void on_vol(GtkRange *r, gpointer u) {
    int pct = (int) gtk_range_get_value(r);
    char cmd[96]; snprintf(cmd, sizeof cmd, "amixer -q sset Master %d%%", pct);
    run_async(cmd);
}
static GtkWidget *build_sound(void) {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    gtk_box_pack_start(GTK_BOX(v), page_title("Sound"), FALSE, FALSE, 0);
    GtkWidget *c = card();
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_style_context_add_class(gtk_widget_get_style_context(row), "row");
    GtkWidget *k = gtk_label_new("Output volume");
    gtk_widget_set_halign(k, GTK_ALIGN_START);
    gtk_style_context_add_class(gtk_widget_get_style_context(k), "k");
    GtkWidget *sl = gtk_scale_new_with_range(GTK_ORIENTATION_HORIZONTAL, 0, 100, 1);
    gtk_range_set_value(GTK_RANGE(sl), 70);
    gtk_scale_set_draw_value(GTK_SCALE(sl), FALSE);
    gtk_widget_set_hexpand(sl, TRUE); gtk_widget_set_size_request(sl, 220, -1);
    g_signal_connect(sl, "value-changed", G_CALLBACK(on_vol), NULL);
    gtk_box_pack_start(GTK_BOX(row), k, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(row), sl, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(c), row, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), c, FALSE, FALSE, 0);
    return page_scroll(v);
}

/* ---- Network ---- */
static GtkWidget *build_network(void) {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    gtk_box_pack_start(GTK_BOX(v), page_title("Network"), FALSE, FALSE, 0);
    GtkWidget *c = card();
    GDir *d = g_dir_open("/sys/class/net", 0, NULL);
    int any = 0;
    if (d) { const char *ifn;
        while ((ifn = g_dir_read_name(d))) {
            if (!strcmp(ifn, "lo")) continue;
            char p[256];
            snprintf(p, sizeof p, "/sys/class/net/%s/operstate", ifn);
            char *st = slurp(p);
            add_kv(c, ifn, st ? st : "unknown"); g_free(st); any = 1;
        }
        g_dir_close(d);
    }
    if (!any) add_kv(c, "Interfaces", "none");
    gtk_box_pack_start(GTK_BOX(v), c, FALSE, FALSE, 0);
    GtkWidget *note = gtk_label_new("Wi-Fi management is coming to AuroraOS. "
        "Wired/NAT networking is active by default in the VM.");
    gtk_widget_set_halign(note, GTK_ALIGN_START);
    gtk_label_set_line_wrap(GTK_LABEL(note), TRUE);
    gtk_style_context_add_class(gtk_widget_get_style_context(note), "note");
    gtk_box_pack_start(GTK_BOX(v), note, FALSE, FALSE, 0);
    return page_scroll(v);
}

/* ---- Power ---- */
static void pw_restart(GtkButton *b, gpointer u)  { run_async("systemctl reboot"); }
static void pw_shutdown(GtkButton *b, gpointer u) { run_async("systemctl poweroff"); }
static GtkWidget *build_power(void) {
    GtkWidget *v = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    gtk_box_pack_start(GTK_BOX(v), page_title("Power"), FALSE, FALSE, 0);
    GtkWidget *c = card();
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_widget_set_margin_top(row, 6); gtk_widget_set_margin_bottom(row, 6);
    gtk_widget_set_margin_start(row, 14); gtk_widget_set_margin_end(row, 14);
    GtkWidget *rb = gtk_button_new_with_label("↻  Restart");
    GtkWidget *sb = gtk_button_new_with_label("⏻  Shut Down");
    gtk_style_context_add_class(gtk_widget_get_style_context(rb), "pw");
    gtk_style_context_add_class(gtk_widget_get_style_context(sb), "pw");
    gtk_style_context_add_class(gtk_widget_get_style_context(sb), "danger");
    g_signal_connect(rb, "clicked", G_CALLBACK(pw_restart), NULL);
    g_signal_connect(sb, "clicked", G_CALLBACK(pw_shutdown), NULL);
    gtk_box_pack_start(GTK_BOX(row), rb, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(row), sb, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(c), row, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(v), c, FALSE, FALSE, 0);
    return page_scroll(v);
}

static const char *CSS =
"window { background-color: #0a0e1a; }"
"label { color: #eef1f8; font-family: 'Noto Sans', sans-serif; }"
"stacksidebar { background-color: rgba(13,16,28,0.96); border-right: 1px solid rgba(255,255,255,0.08); }"
"stacksidebar list { background: transparent; }"
"stacksidebar row { padding: 10px 16px; border-radius: 10px; margin: 3px 8px; }"
"stacksidebar row:selected { background-color: rgba(52,224,200,0.18); }"
"stacksidebar label { color: #dfe5f0; font-size: 13.5px; }"
".ptitle { font-size: 20px; font-weight: 700; }"
".card { background-color: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.09); border-radius: 14px; }"
".row { padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }"
".k { color: #98a2ba; font-size: 13.5px; }"
".v { color: #eef1f8; font-size: 13.5px; }"
".note { color: #98a2ba; font-size: 12.5px; }"
".hero { padding: 18px; }"
".hname { font-size: 26px; font-weight: 800; }"
".hver { color: #98a2ba; font-size: 14px; }"
"scale trough { background-color: rgba(255,255,255,0.14); border-radius: 99px; min-height: 6px; }"
"scale highlight { background-color: #34e0c8; border-radius: 99px; }"
"scale slider { background-color: #fff; border-radius: 50%; min-width: 16px; min-height: 16px; margin: -6px; }"
".pw { background-image: none; background-color: rgba(255,255,255,0.08); color: #eef1f8; border: 1px solid rgba(255,255,255,0.12); box-shadow: none; padding: 12px; border-radius: 12px; font-size: 14px; }"
".pw:hover { background-color: rgba(255,255,255,0.13); }"
".danger { color: #f7768e; }"
".danger:hover { background-color: rgba(247,118,142,0.16); }";

static void activate(GtkApplication *app, gpointer u) {
    GtkCssProvider *p = gtk_css_provider_new();
    gtk_css_provider_load_from_data(p, CSS, -1, NULL);
    gtk_style_context_add_provider_for_screen(gdk_screen_get_default(),
        GTK_STYLE_PROVIDER(p), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);

    GtkWidget *win = gtk_application_window_new(app);
    gtk_window_set_title(GTK_WINDOW(win), "Settings");
    gtk_window_set_default_size(GTK_WINDOW(win), 720, 500);

    GtkWidget *hb = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    GtkWidget *stack = gtk_stack_new();
    gtk_stack_set_transition_type(GTK_STACK(stack), GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    GtkWidget *side = gtk_stack_sidebar_new();
    gtk_stack_sidebar_set_stack(GTK_STACK_SIDEBAR(side), GTK_STACK(stack));
    gtk_widget_set_size_request(side, 180, -1);

    gtk_stack_add_titled(GTK_STACK(stack), build_about(),   "about",   "About");
    gtk_stack_add_titled(GTK_STACK(stack), build_display(), "display", "Display");
    gtk_stack_add_titled(GTK_STACK(stack), build_sound(),   "sound",   "Sound");
    gtk_stack_add_titled(GTK_STACK(stack), build_network(), "network", "Network");
    gtk_stack_add_titled(GTK_STACK(stack), build_power(),   "power",   "Power");

    gtk_widget_set_hexpand(stack, TRUE);
    gtk_box_pack_start(GTK_BOX(hb), side, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(hb), stack, TRUE, TRUE, 0);
    gtk_container_add(GTK_CONTAINER(win), hb);
    gtk_widget_show_all(win);
}

int main(int argc, char **argv) {
    GtkApplication *app = gtk_application_new("os.aurora.Settings", G_APPLICATION_DEFAULT_FLAGS);
    g_signal_connect(app, "activate", G_CALLBACK(activate), NULL);
    int status = g_application_run(G_APPLICATION(app), argc, argv);
    g_object_unref(app);
    return status;
}
