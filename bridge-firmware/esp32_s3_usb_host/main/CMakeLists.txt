idf_component_register(
    SRCS
        "main.c"
        "wifi_station.c"
        "tcp_single_client.c"
        "control_server.c"
        "bridge_storage.c"
        "usb_msp_transport.c"
        "usb_msc_blackbox.c"
    INCLUDE_DIRS "."
)

