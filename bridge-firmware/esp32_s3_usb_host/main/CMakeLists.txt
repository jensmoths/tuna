idf_component_register(
    SRCS
        "main.c"
        "wifi_station.c"
        "tcp_single_client.c"
        "control_server.c"
        "bridge_storage.c"
        "usb_msp_transport.c"
        "usb_msc_blackbox.c"
        "usb_host_common.c"
        "board_power.c"
    INCLUDE_DIRS "."
)

if(DEFINED ENV{BRIDGE_WIFI_SSID})
    target_compile_definitions(${COMPONENT_LIB} PRIVATE BRIDGE_WIFI_SSID="$ENV{BRIDGE_WIFI_SSID}")
endif()

if(DEFINED ENV{BRIDGE_WIFI_PASSWORD})
    target_compile_definitions(${COMPONENT_LIB} PRIVATE BRIDGE_WIFI_PASSWORD="$ENV{BRIDGE_WIFI_PASSWORD}")
endif()

