#!/bin/sh
python3 monitor.py &
./xray -config config.json
