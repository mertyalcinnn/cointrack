from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
import asyncio
from typing import Optional, List, Dict

from src.analysis.price_analysis import PriceAnalyzer
from src.data_collectors.coingecko import CoinGeckoAPI
from src.analysis.ai_analyzer import AIAnalyzer

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS ayarları (Sadece belirli domainlere izin veriyoruz)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Statik dosyalar için klasör
app.mount("/static", StaticFiles(directory="static"), name="static")

# Servisler
analyzer = PriceAnalyzer()
coingecko = CoinGeckoAPI()
ai_analyzer = AIAnalyzer(logger)  # AI analiz servisi

# AI Analyzer'ı başlatma işlemini asenkron olarak yönet
@app.on_event("startup")
async def startup_event():
    global ai_analyzer
    try:
        # Web araştırma modülünü başlat
        await ai_analyzer.initialize()
        logger.info("AI Analyzer başarıyla başlatıldı.")
    except Exception as e:
        logger.error(f"AI Analyzer başlatma hatası: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    global ai_analyzer
    try:
        # Kaynakları temizle
        logger.info("Uygulama kapanıyor, kaynaklar temizleniyor...")
        await ai_analyzer.close()
        logger.info("AI Analyzer kaynakları temizlendi.")
        
        # Ek temizlik işlemleri
        import asyncio
        pending = asyncio.all_tasks()
        for task in pending:
            if not task.done() and task != asyncio.current_task():
                logger.info(f"Bekleyen görev iptal ediliyor: {task.get_name()}")
                task.cancel()
        
        logger.info("Tüm kaynaklar temizlendi, uygulama güvenli bir şekilde kapanıyor")
    except Exception as e:
        logger.error(f"Uygulama kapatılırken hata: {e}")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html") as f:
        return f.read()

@app.get("/api/analysis/price")
async def get_price_analysis(
    coin: str = Query("bitcoin", description="Kripto para birimi ID'si"),
    period: str = Query("24h", description="Analiz periyodu (24h, 7d, 30d, 90d)")
):
    try:
        logger.info(f"Fiyat analizi isteği alındı - Coin: {coin}, Period: {period}")
        
        # Period'u gün sayısına çevir
        days_map = {
            "24h": 1,
            "7d": 7,
            "30d": 30,
            "90d": 90
        }
        days = days_map.get(period, 1)
        
        # Coin verilerini al
        price_data = coingecko.get_price_history(coin_id=coin, days=days)
        if not price_data:
            logger.warning(f"Fiyat verisi alınamadı: {coin}, {days} gün")
            price_data = []  # Boş liste döndürelim

        current_data = coingecko.get_current_data(coin_id=coin)
        if not current_data:
            logger.warning(f"Güncel fiyat verisi alınamadı: {coin}")
            current_data = {"current_price": 0, "price_change_24h": 0, "last_updated": ""}

        logger.info(f"CoinGecko'dan {len(price_data)} adet fiyat verisi alındı")
        
        # Trend analizi yap
        analysis = analyzer.analyze_price_trend(price_data)
        
        # Güncel fiyat bilgilerini ekle
        if current_data:
            analysis.update(current_data)
        else:
            logger.warning("current_data boş döndü, analiz sonuçlarına eklenemedi.")

        logger.info(f"Analiz sonucu: {analysis}")
        return JSONResponse(content=analysis)
        
    except Exception as e:
        logger.error(f"Hata oluştu: {str(e)}")
        return JSONResponse(
            content={
                "trend": "NEUTRAL",
                "confidence": 0,
                "price_change_24h": 0,
                "current_price": 0,
                "last_updated": "",
                "error": str(e)
            },
            status_code=200
        )

@app.get("/api/analysis/ai")
async def get_ai_analysis(
    symbol: str = Query("BTC", description="Kripto para birimi sembolü (BTC, ETH, vb.)"),
    include_research: bool = Query(False, description="Web araştırma verilerini dahil et")
):
    try:
        logger.info(f"AI analizi isteği alındı - Symbol: {symbol}, Include Research: {include_research}")
        
        # Teknik analiz verilerini hazırla
        technical_data = {
            "symbol": symbol,
            "opportunity_score": 50,  # Başlangıç skoru
        }
        
        # Güncel fiyat verilerini ekle
        try:
            # CoinGecko formatını symbol'e dönüştürme
            coin_id_map = {
                "BTC": "bitcoin",
                "ETH": "ethereum",
                "SOL": "solana",
                "BNB": "binancecoin",
                "XRP": "ripple"
            }
            
            coin_id = coin_id_map.get(symbol.upper(), symbol.lower())
            current_data = coingecko.get_current_data(coin_id=coin_id)
            
            if current_data:
                technical_data.update({
                    "current_price": current_data.get("current_price", 0),
                    "price_change_24h": current_data.get("price_change_24h", 0),
                    "last_updated": current_data.get("last_updated", "")
                })
                
                # Basit trend analizi ekle
                if current_data.get("price_change_24h", 0) > 0:
                    technical_data["hourly_trend"] = "YUKARI"
                else:
                    technical_data["hourly_trend"] = "AŞAĞI"
        except Exception as price_error:
            logger.error(f"Fiyat verisi alınırken hata: {price_error}")
        
        # AI analizi yap
        result = await ai_analyzer.analyze_opportunity(symbol, technical_data)
        
        # Eğer istenirse web araştırma verilerini ekle
        if include_research:
            research_data = await ai_analyzer.get_deep_web_research(symbol)
            result["web_research"] = research_data
        
        logger.info(f"AI analizi tamamlandı - Symbol: {symbol}")
        return JSONResponse(content=result)
        
    except Exception as e:
        logger.error(f"AI analizi sırasında hata: {str(e)}")
        return JSONResponse(
            content={
                "symbol": symbol,
                "fundamental_score": 0,
                "analysis": f"Analiz yapılırken bir hata oluştu: {str(e)}",
                "recommendation": "BEKLE",
                "error": str(e)
            },
            status_code=200
        )

@app.get("/api/research/web")
async def get_web_research(
    symbol: str = Query("BTC", description="Kripto para birimi sembolü (BTC, ETH, vb.)")
):
    try:
        logger.info(f"Web araştırması isteği alındı - Symbol: {symbol}")
        
        # Web araştırması yap
        research_data = await ai_analyzer.get_deep_web_research(symbol)
        
        logger.info(f"Web araştırması tamamlandı - Symbol: {symbol}")
        return JSONResponse(content=research_data)
        
    except Exception as e:
        logger.error(f"Web araştırması sırasında hata: {str(e)}")
        return JSONResponse(
            content={
                "symbol": symbol,
                "error": str(e)
            },
            status_code=200
        )

@app.get("/api/analysis/multiple")
async def analyze_multiple_coins(
    symbols: str = Query("BTC,ETH,SOL,XRP,BNB", description="Virgülle ayrılmış kripto para birimi sembolleri")
):
    try:
        # Sembolleri parse et
        coin_symbols = [s.strip().upper() for s in symbols.split(",")]
        logger.info(f"Çoklu coin analizi isteği alındı - Semboller: {coin_symbols}")
        
        # Her bir coin için teknik veri hazırla
        opportunities = []
        
        # CoinGecko ID dönüşüm haritası
        coin_id_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "BNB": "binancecoin",
            "XRP": "ripple"
        }
        
        for symbol in coin_symbols:
            try:
                coin_id = coin_id_map.get(symbol, symbol.lower())
                current_data = coingecko.get_current_data(coin_id=coin_id)
                
                opp = {
                    "symbol": symbol,
                    "opportunity_score": 50
                }
                
                if current_data:
                    opp.update({
                        "current_price": current_data.get("current_price", 0),
                        "price_change_24h": current_data.get("price_change_24h", 0)
                    })
                    
                    # Fiyat değişimine göre fırsat puanı ayarla
                    price_change = current_data.get("price_change_24h", 0)
                    if price_change > 5:
                        opp["opportunity_score"] = 70
                    elif price_change > 0:
                        opp["opportunity_score"] = 60
                    elif price_change < -5:
                        opp["opportunity_score"] = 30
                    elif price_change < 0:
                        opp["opportunity_score"] = 40
                
                opportunities.append(opp)
            except Exception as coin_error:
                logger.error(f"{symbol} için veri hazırlanırken hata: {coin_error}")
                opportunities.append({
                    "symbol": symbol,
                    "opportunity_score": 50,
                    "error": str(coin_error)
                })
        
        # Tüm coinler için paralel analiz yap
        results = await ai_analyzer.analyze_multiple_coins(opportunities)
        
        logger.info(f"{len(results)} coin için analiz tamamlandı")
        return JSONResponse(content=results)
        
    except Exception as e:
        logger.error(f"Çoklu coin analizi sırasında hata: {str(e)}")
        return JSONResponse(
            content={
                "error": str(e),
                "coins": []
            },
            status_code=200
        )