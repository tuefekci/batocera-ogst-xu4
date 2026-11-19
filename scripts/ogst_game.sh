#!/bin/bash
case "$1" in
    gameStart)
        python3 /userdata/system/ogst_display.py game_start "$2" "$3" "$5" &
        ;;
    gameStop)
        python3 /userdata/system/ogst_display.py game_stop &
        ;;
esac
