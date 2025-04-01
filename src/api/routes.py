from flask import Blueprint, jsonify
from src.analysis.price_analysis import PriceAnalyzer

api = Blueprint('api', __name__)
analyzer = PriceAnalyzer()

@api.route('/analysis/price', methods=['GET'])
def get_price_analysis():
    # CoinGecko'dan veri alma işlemi burada yapılacak
    price_data = []  # Gerçek veriyi buraya ekleyeceğiz
    
    analysis = analyzer.analyze_price_trend(price_data)
    return jsonify(analysis)

@api.route('/analysis/breakout', methods=['GET'])
def get_breakout_analysis():
    price_data = []  # Gerçek veriyi buraya ekleyeceğiz
    
    breakout = analyzer.detect_breakout(price_data)
    return jsonify(breakout if breakout else {})