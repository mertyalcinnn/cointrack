# Kaldıraç seviyesini belirle
def determine_leverage(ai_score):
    if ai_score > 85:
        return min(10, CONFIG['max_leverage'])
    elif ai_score > 75:
        return min(7, CONFIG['max_leverage'])
    elif ai_score > 65:
        return min(5, CONFIG['max_leverage'])
    else:
        return 3

# İşlem fırsatı analiz et
def analyze_opportunity(exchange, symbol):
    # AI analizi al
    logger.debug(f"AI analizi başlatılıyor: {symbol}")
    ai_result = get_ai_analysis(exchange, symbol)
    
    if not ai_result:
        logger.debug(f"{symbol} için AI analizi alınamadı")
        return None
    
    logger.debug(f"AI Analiz Sonucu ({symbol}): {ai_result}")
    
    # Teknik sinyalleri al
    logger.debug(f"Teknik analiz başlatılıyor: {symbol}")
    tech_signals = get_technical_signals(exchange, symbol)
    logger.debug(f"Teknik Analiz Sonucu ({symbol}): {tech_signals}")
    
    # AI tavsiyesini dönüştür
    if ai_result['recommendation'] == 'BUY':
        ai_recommendation = 'AL'
    elif ai_result['recommendation'] == 'SELL':
        ai_recommendation = 'SAT'
    else:
        ai_recommendation = 'BEKLE'
    
    logger.debug(f"{symbol} AI Tavsiyesi: {ai_recommendation}")
    
    # Toplam skoru hesapla
    ai_score = ai_result['confidence']
    tech_score = 0
    
    if tech_signals['overall'] == 'STRONG_LONG':
        tech_score = 30
    elif tech_signals['overall'] == 'LONG':
        tech_score = 20
    elif tech_signals['overall'] == 'STRONG_SHORT':
        tech_score = -30
    elif tech_signals['overall'] == 'SHORT':
        tech_score = -20
    
    logger.debug(f"{symbol} Tech Skor: {tech_score}, AI Skor: {ai_score}")
    
    # İşlem yönünü belirle
    if tech_signals['overall'] in ['LONG', 'STRONG_LONG'] and ai_recommendation == 'AL':
        direction = 'LONG'
        score = ai_score + abs(tech_score)
        logger.debug(f"{symbol} LONG sinyali bulundu. Toplam skor: {score}")
    elif tech_signals['overall'] in ['SHORT', 'STRONG_SHORT'] and ai_recommendation == 'SAT':
        direction = 'SHORT'
        score = ai_score + abs(tech_score)
        logger.debug(f"{symbol} SHORT sinyali bulundu. Toplam skor: {score}")
    else:
        # Uyumsuz sinyaller
        logger.debug(f"{symbol} için uyumsuz sinyaller: Teknik={tech_signals['overall']}, AI={ai_recommendation}")
        return None
    
    # Min skor kontrolü
    if score < CONFIG['min_ai_score']:
        logger.debug(f"{symbol} toplam skoru ({score}) minimum skor eşiğinin ({CONFIG['min_ai_score']}) altında")
        return None
        
    return {
        'symbol': symbol,
        'direction': direction,
        'ai_recommendation': ai_recommendation,
        'ai_confidence': ai_score,
        'tech_signal': tech_signals['overall'],
        'total_score': score,
        'timestamp': datetime.now().isoformat()
    }

# Pozisyon aç
def open_position(exchange, open_positions, opportunity):
    try:
        # Sembol için geçerli piyasa fiyatını al
        ticker = exchange.fetch_ticker(opportunity['symbol'])
        current_price = ticker['last']
        
        # Kaldıraç seviyesini belirle
        leverage = determine_leverage(opportunity['ai_confidence'])
        
        # Kaldıracı ayarla
        exchange.set_leverage(leverage, opportunity['symbol'])
        
        # Pozisyon büyüklüğünü hesapla
        amount = CONFIG['position_size_usd'] * leverage / current_price
        
        # İşlem yönünü belirle
        side = 'buy' if opportunity['direction'] == 'LONG' else 'sell'
        
        # Kar ve zarar seviyelerini hesapla
        if side == 'buy':
            take_profit_price = current_price * (1 + (CONFIG['profit_target_usd'] / (CONFIG['position_size_usd'] * leverage)))
            stop_loss_price = current_price * (1 - (CONFIG['max_loss_usd'] / (CONFIG['position_size_usd'] * leverage)))
        else:
            take_profit_price = current_price * (1 - (CONFIG['profit_target_usd'] / (CONFIG['position_size_usd'] * leverage)))
            stop_loss_price = current_price * (1 + (CONFIG['max_loss_usd'] / (CONFIG['position_size_usd'] * leverage)))
        
        # İşlemi aç
        order = exchange.create_market_order(
            symbol=opportunity['symbol'],
            side=side,
            amount=amount,
            params={}
        )
        
        # Pozisyon bilgilerini kaydet
        position = {
            'symbol': opportunity['symbol'],
            'id': order['id'],
            'side': side,
            'amount': amount,
            'entry_price': current_price,
            'take_profit': take_profit_price,
            'stop_loss': stop_loss_price,
            'leverage': leverage,
            'opened_at': datetime.now().isoformat(),
            'opportunity': opportunity
        }
        
        open_positions.append(position)
        
        # İşlem geçmişini güncelle
        trade_history = load_trade_history()
        trade_history.append({
            'action': 'OPEN',
            'position': position,
            'timestamp': datetime.now().isoformat()
        })
        save_trade_history(trade_history)
        
        logger.info(f"Pozisyon açıldı: {opportunity['symbol']} {side.upper()} - Kaldıraç: {leverage}x - Giriş: {current_price} - TP: {take_profit_price} - SL: {stop_loss_price}")
        
        # Telegram bildirimini gönder
        send_telegram_message(
            f"🚀 *POZİSYON AÇILDI*\n\n"
            f"💰 Sembol: {opportunity['symbol']}\n"
            f"📈 Yön: {side.upper()}\n"
            f"⚖️ Kaldıraç: {leverage}x\n"
            f"💵 Giriş Fiyatı: ${current_price:.6f}\n"
            f"🎯 Kar Hedefi: ${take_profit_price:.6f}\n"
            f"🛑 Stop Loss: ${stop_loss_price:.6f}\n\n"
            f"⭐ AI Skoru: {opportunity['ai_confidence']}\n"
            f"📊 Teknik Sinyal: {opportunity['tech_signal']}\n"
        )
        
        return position
    except Exception as e:
        logger.error(f"Pozisyon açılamadı: {e}")
        return None

# Pozisyon kapat
def close_position(exchange, open_positions, position, reason):
    try:
        # Ters işlem yönü
        close_side = 'sell' if position['side'] == 'buy' else 'buy'
        
        # Pozisyonu kapat
        order = exchange.create_market_order(
            symbol=position['symbol'],
            side=close_side,
            amount=position['amount'],
            params={}
        )
        
        # Güncel fiyatı al
        ticker = exchange.fetch_ticker(position['symbol'])
        exit_price = ticker['last']
        
        # PnL hesapla
        if position['side'] == 'buy':
            pnl = (exit_price - position['entry_price']) * position['amount'] * position['leverage']
        else:
            pnl = (position['entry_price'] - exit_price) * position['amount'] * position['leverage']
        
        # Kapatma bilgilerini kaydet
        close_data = {
            'exit_price': exit_price,
            'pnl': pnl,
            'closed_at': datetime.now().isoformat(),
            'reason': reason
        }
        
        # Pozisyon listesini güncelle
        for i, p in enumerate(open_positions):
            if p['id'] == position['id']:
                open_positions.pop(i)
                break
        
        # İşlem geçmişini güncelle
        trade_history = load_trade_history()
        trade_history.append({
            'action': 'CLOSE',
            'position': {**position, **close_data},
            'timestamp': datetime.now().isoformat()
        })
        save_trade_history(trade_history)
        
        logger.info(f"Pozisyon kapatıldı: {position['symbol']} - Çıkış: {exit_price} - PnL: ${pnl:.2f} - Neden: {reason}")
        
        # Telegram bildirimini gönder
        kar_zarar_emoji = "💰" if pnl >= 0 else "💴"
        send_telegram_message(
            f"{kar_zarar_emoji} *POZİSYON KAPATILDI*\n\n"
            f"💰 Sembol: {position['symbol']}\n"
            f"📈 Yön: {position['side'].upper()}\n"
            f"💵 Giriş Fiyatı: ${position['entry_price']:.6f}\n"
            f"💵 Çıkış Fiyatı: ${exit_price:.6f}\n"
            f"{kar_zarar_emoji} {'KÂR' if pnl >= 0 else 'ZARAR'}: ${abs(pnl):.2f}\n\n"
            f"🚫 Neden: {reason}\n"
        )
        
        return {**position, **close_data}
    except Exception as e:
        logger.error(f"Pozisyon kapatılamadı: {e}")
        return None

# Pozisyonları kontrol et
def check_positions(exchange, open_positions):
    for position in list(open_positions):
        try:
            # Güncel fiyatı al
            ticker = exchange.fetch_ticker(position['symbol'])
            current_price = ticker['last']
            
            # Pozisyon yaşını kontrol et
            opened_at = datetime.fromisoformat(position['opened_at'])
            position_age = (datetime.now() - opened_at).total_seconds()
            
            # Kar hedefine ulaşıldı mı?
            if (position['side'] == 'buy' and current_price >= position['take_profit']) or \
               (position['side'] == 'sell' and current_price <= position['take_profit']):
                close_position(exchange, open_positions, position, "Kar hedefine ulaşıldı")
            
            # Zarar limitine ulaşıldı mı?
            elif (position['side'] == 'buy' and current_price <= position['stop_loss']) or \
                 (position['side'] == 'sell' and current_price >= position['stop_loss']):
                close_position(exchange, open_positions, position, "Zarar limitine ulaşıldı")
            
            # Maksimum pozisyon yaşını aştı mı?
            elif position_age > CONFIG['max_position_age']:
                close_position(exchange, open_positions, position, "Maksimum süre aşıldı")
                
        except Exception as e:
            logger.error(f"Pozisyon kontrolü sırasında hata: {e}")

# Piyasayı tara ve işlem yap
def scan_market(exchange, open_positions):
    try:
        # Tüm semboller
        logger.debug("Piyasa taraması başlatılıyor")
        markets = exchange.load_markets()
        top_symbols = [
            'BTC/USDT:USDT', 'ETH/USDT:USDT', 'BNB/USDT:USDT',
            'SOL/USDT:USDT', 'XRP/USDT:USDT', 'ADA/USDT:USDT',
            'AVAX/USDT:USDT', 'MATIC/USDT:USDT', 'DOGE/USDT:USDT',
            'DOT/USDT:USDT', 'SHIB/USDT:USDT', 'LTC/USDT:USDT',
            'NEAR/USDT:USDT', 'FTM/USDT:USDT', 'ATOM/USDT:USDT',
            'LINK/USDT:USDT', 'UNI/USDT:USDT', 'ALGO/USDT:USDT'
        ]
        
        logger.debug(f"Taranacak semboller: {top_symbols}")
        
        # İşlem fırsatları
        opportunities = []
        
        # Her bir sembol için işlem fırsatı analiz et
        for symbol in top_symbols:
            logger.debug(f"{symbol} analizi başlatılıyor")
            opportunity = analyze_opportunity(exchange, symbol)
            if opportunity and opportunity['total_score'] >= CONFIG['min_ai_score']:
                opportunities.append(opportunity)
                logger.info(f"İşlem fırsatı bulundu: {symbol} - Yön: {opportunity['direction']} - Skor: {opportunity['total_score']}")
            else:
                logger.debug(f"{symbol} için işlem fırsatı bulunamadı")
        
        # Fırsatları skora göre sırala
        opportunities.sort(key=lambda x: x['total_score'], reverse=True)
        logger.debug(f"Toplam {len(opportunities)} fırsat bulundu")
        
        # En iyi 3 fırsatı seç
        top_opportunities = opportunities[:3]
        
        # Açık pozisyon sayısını kontrol et
        if len(open_positions) < CONFIG['max_positions'] and top_opportunities:
            # Zaten açık olan sembolleri kontrol et
            open_symbols = [p['symbol'] for p in open_positions]
            for opportunity in top_opportunities:
                if opportunity['symbol'] not in open_symbols:
                    logger.debug(f"Pozisyon açma kriterleri karşılandı: {opportunity['symbol']}")
                    open_position(exchange, open_positions, opportunity)
                    break  # Her döngüde sadece bir pozisyon aç
                else:
                    logger.debug(f"{opportunity['symbol']} için zaten açık pozisyon var")
        else:
            if len(open_positions) >= CONFIG['max_positions']:
                logger.debug(f"Maksimum pozisyon sayısına ulaşıldı: {len(open_positions)}/{CONFIG['max_positions']}")
            elif not top_opportunities:
                logger.debug("Uygun işlem fırsatı bulunamadı")
    
    except Exception as e:
        logger.error(f"Piyasa tarama sırasında hata: {e}")
        import traceback
        logger.error(traceback.format_exc())

# Ana fonksiyon
def main():
    logger.info("Otomatik Kaldıraçlı İşlem Sistemi başlatılıyor")
    
    print("Telegram ayarları kontrol ediliyor...")
    telegram_ready = setup_telegram()
    if telegram_ready:
        print("Telegram bildirimleri aktif")
    else:
        print("Telegram bildirimleri devre dışı")
    
    # Binance bağlantısını kur
    print("Binance API bağlantısı kuruluyor...")
    exchange = setup_binance()
    if not exchange:
        error_msg = "Binance API bağlantısı kurulamadı, program sonlandırılıyor"
        logger.error(error_msg)
        print(error_msg)
        return
    
    # Başlangıç bildirimi
    start_msg = (
        "🚀 *Otomatik Kaldıraçlı İşlem Sistemi Başlatıldı*\n\n"
        "💰 Sistem şu anda piyasayı tarayarak işlem fırsatlarını arıyor.\n\n"
        "⚙️ Ayarlar:\n"
        f"- Maksimum Pozisyon Sayısı: {CONFIG['max_positions']}\n"
        f"- Pozisyon Büyüklüğü: ${CONFIG['position_size_usd']}\n"
        f"- Maksimum Kaldıraç: {CONFIG['max_leverage']}x\n"
        f"- Risk/Ödül: {CONFIG['max_loss_usd']}$ / {CONFIG['profit_target_usd']}$\n\n"
        "⏰ Her 5 dakikada bir piyasa taraması yapılacak ve uygun fırsatlar bulunduğunda otomatik işlemler açılacak.\n"
        "⚠️ Sistemi durdurmak için /stopautoscan komutunu kullanın."
    )
    
    send_telegram_message(start_msg)
    
    # Açık pozisyonlar listesi
    open_positions = []
    
    try:
        # Ana döngü
        while True:
            # Pozisyonları kontrol et
            check_positions(exchange, open_positions)
            
            # Piyasayı tara
            scan_market(exchange, open_positions)
            
            # Bekleme süresi
            print(f"{CONFIG['scan_interval']} saniye bekleniyor...")
            logger.info(f"{CONFIG['scan_interval']} saniye bekleniyor...")
            time.sleep(CONFIG['scan_interval'])
    
    except KeyboardInterrupt:
        print("Program kullanıcı tarafından durduruldu.")
        logger.info("Program kullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"Program bir hata nedeniyle durdu: {e}")
        logger.error(f"Program bir hata nedeniyle durdu: {e}")
        import traceback
        error_msg = traceback.format_exc()
        logger.error(f"Hata detayları:\n{error_msg}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Beklenmeyen hata: {e}")
        print(f"Beklenmeyen hata: {e}")
