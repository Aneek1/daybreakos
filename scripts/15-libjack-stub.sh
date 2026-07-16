#!/bin/bash
# DaybreakOS script 15 — libjack.so.0 stub.
# DaybreakOS ships no JACK audio server, but some prebuilt apps (e.g. Xournal++'s
# bundled libportaudio) hard-link libjack.so.0. Provide a stub: every entry
# point returns 0/NULL, so jack_client_open() reports "no server" and callers
# fall back to ALSA. Satisfies both load-time NEEDED and call-time symbol bind.
set -e
SYMS="jack_activate jack_client_close jack_client_name_size jack_client_open \
jack_connect jack_deactivate jack_frame_time jack_get_buffer_size \
jack_get_client_name jack_get_ports jack_get_sample_rate jack_on_shutdown \
jack_port_by_name jack_port_connected jack_port_disconnect jack_port_get_buffer \
jack_port_get_latency jack_port_name jack_port_name_size jack_port_register \
jack_port_unregister jack_set_error_function jack_set_process_callback \
jack_set_sample_rate_callback jack_set_xrun_callback"

mkdir -p /tmp/jackstub
{
  echo '/* DaybreakOS libjack.so.0 stub */'
  for s in $SYMS; do echo "void *$s(void){return 0;}"; done
} > /tmp/jackstub/jackstub.c
gcc -shared -fPIC -Wl,-soname,libjack.so.0 -o /usr/lib/libjack.so.0.0.0 /tmp/jackstub/jackstub.c
ln -sf libjack.so.0.0.0 /usr/lib/libjack.so.0
ln -sf libjack.so.0     /usr/lib/libjack.so
/usr/sbin/ldconfig
echo "libjack stub installed: $(nm -D /usr/lib/libjack.so.0 | grep -c ' T jack_') symbols"
