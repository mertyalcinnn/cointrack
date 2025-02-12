from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
from typing import Optional

from src.analysis.price_analysis import PriceAnalyzer
from src.data_collectors.coingecko import CoinGeckoAPI

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