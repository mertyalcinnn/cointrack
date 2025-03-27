#!/bin/bash

echo "Kripto Sinyal Bot İyileştirmelerini Uygulama Betiği"
echo "=================================================="
echo ""

echo "1. MultiTimeframeAnalyzer modülü parçalarını birleştirme..."
python3 combine_multi_timeframe_modules.py
echo ""

echo "2. MultiTimeframeHandler modülü parçalarını birleştirme..."
python3 combine_handlers.py
echo ""

echo "3. İzinleri ayarlama..."
chmod +x combine_*.py
chmod +x apply_improvements.sh
echo ""

echo "İyileştirmeler tamamlandı!"
echo "Botu şimdi başlatabilirsiniz."
