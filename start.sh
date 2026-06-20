#!/bin/sh

# نشغلوا السكربت تاع المراقبة في الخلفية باستخدام &
python3 monitor.py &

# نشغلوا الـ Xray في الواجهة الأمامية (بدون &)
# هكذا السكربت ماراحش يكمل (exit) حتى يطفى الـ Xray
./xray run -config config.json
