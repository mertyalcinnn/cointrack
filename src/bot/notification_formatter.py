class TradingViewFormatter:
    def format_analysis(self, analysis: Dict) -> str:
        """TradingView tarzı analiz formatı"""
        try:
            return f"""📊 {analysis['symbol']} Teknik Analiz
            
📈 Trend Durumu:
• EMA (20): {analysis['trend']['ema']['20']}
• SuperTrend: {analysis['trend']['supertrend']['direction']}
• ADX: {analysis['trend']['adx']} ({'Güçlü' if analysis['trend']['adx'] > 25 else 'Zayıf'})

📊 Momentum:
• RSI: {analysis['momentum']['rsi']:.2f}
• Stochastic: %K({analysis['momentum']['stochastic']['k']:.1f}) %D({analysis['momentum']['stochastic']['d']:.1f})
• MACD: {'Pozitif' if analysis['momentum']['macd']['histogram'] > 0 else 'Negatif'}

💹 Hacim Analizi:
• OBV: {'Artıyor' if analysis['volume']['obv'] > 0 else 'Azalıyor'}
• MFI: {analysis['volume']['mfi']:.2f}
• VWAP: ${analysis['volume']['vwap']:.2f}

📍 Önemli Seviyeler:
• Pivot: ${analysis['custom']['pivot_points']['pivot']:.2f}
• R1: ${analysis['custom']['pivot_points']['r1']:.2f}
• S1: ${analysis['custom']['pivot_points']['s1']:.2f}

⚡️ Volatilite:
• BB Üst: ${analysis['volatility']['bollinger']['upper']:.2f}
• BB Alt: ${analysis['volatility']['bollinger']['lower']:.2f}
• ATR: {analysis['volatility']['atr']:.2f}

🎯 Hacim Profili POC: ${analysis['volume']['volume_profile']['poc']['price_level']:.2f}

{self._get_signal_emoji(analysis)} Sinyal: {self._get_trading_signal(analysis)}"""
            
        except Exception as e:
            return f"Format hatası: {str(e)}" 