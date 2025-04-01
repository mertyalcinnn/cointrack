const { useState, useEffect } = React;

function CryptoDashboard() {
    const [priceData, setPriceData] = useState({
        trend: 'NEUTRAL',
        confidence: 0,
        price_change_24h: 0,
        current_price: 0,
        period: 'SHORT'
    });

    const [selectedCoin, setSelectedCoin] = useState('bitcoin');
    const [selectedPeriod, setSelectedPeriod] = useState('24h');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const coins = [
        { id: 'bitcoin', name: 'Bitcoin (BTC)' },
        { id: 'ethereum', name: 'Ethereum (ETH)' },
        { id: 'binancecoin', name: 'Binance Coin (BNB)' },
        { id: 'ripple', name: 'XRP' },
        { id: 'cardano', name: 'Cardano (ADA)' }
    ];

    const periods = [
        { id: '24h', name: '24 Saat' },
        { id: '7d', name: '7 Gün' },
        { id: '30d', name: '30 Gün' },
        { id: '90d', name: '90 Gün' }
    ];

    useEffect(() => {
        const fetchData = async () => {
            try {
                setLoading(true);
                const response = await fetch(`/api/analysis/price?coin=${selectedCoin}&period=${selectedPeriod}`);
                if (!response.ok) {
                    throw new Error('API yanıt vermedi');
                }
                const data = await response.json();
                setPriceData(data);
                setLoading(false);
            } catch (err) {
                console.error('API Error:', err);
                setError(err.message);
                setLoading(false);
            }
        };

        fetchData();
        const interval = setInterval(fetchData, 60000);
        return () => clearInterval(interval);
    }, [selectedCoin, selectedPeriod]);

    const formatPrice = (price) => {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(price);
    };

    const isDevelopment = window.location.hostname === 'localhost' || 
                         window.location.hostname === '127.0.0.1';

    if (loading) {
        return React.createElement('div', { 
            className: 'min-h-screen bg-gray-100 flex items-center justify-center' 
        }, 
        React.createElement('div', { className: 'loading-spinner' })
        );
    }

    if (error) {
        return React.createElement('div', { 
            className: 'min-h-screen bg-gray-100 flex items-center justify-center text-red-500' 
        }, `Hata: ${error}`);
    }

    return React.createElement('div', { className: 'min-h-screen bg-gray-100 p-8' },
        React.createElement('div', { className: 'max-w-7xl mx-auto' },
            // Başlık ve Kontroller
            React.createElement('div', { className: 'flex flex-col md:flex-row justify-between items-center mb-8' },
                React.createElement('h1', { className: 'text-3xl font-bold mb-4 md:mb-0' }, 'Kripto Analiz Dashboard'),
                React.createElement('div', { className: 'flex flex-col md:flex-row gap-4' },
                    // Coin Seçici
                    React.createElement('select', {
                        className: 'px-4 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500',
                        value: selectedCoin,
                        onChange: (e) => setSelectedCoin(e.target.value)
                    }, coins.map(coin => 
                        React.createElement('option', { key: coin.id, value: coin.id }, coin.name)
                    )),
                    // Periyot Seçici
                    React.createElement('select', {
                        className: 'px-4 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500',
                        value: selectedPeriod,
                        onChange: (e) => setSelectedPeriod(e.target.value)
                    }, periods.map(period => 
                        React.createElement('option', { key: period.id, value: period.id }, period.name)
                    ))
                )
            ),
            
            // Üst Kartlar
            React.createElement('div', { className: 'grid grid-cols-1 md:grid-cols-3 gap-6 mb-8' },
                // Trend Kartı
                React.createElement('div', { className: 'bg-white p-6 rounded-lg shadow-lg' },
                    React.createElement('h2', { className: 'text-sm font-medium text-gray-500 mb-2' }, 'Trend Durumu'),
                    React.createElement('div', { 
                        className: `text-2xl font-bold ${
                            priceData.trend === 'BULLISH' ? 'text-green-500' : 
                            priceData.trend === 'BEARISH' ? 'text-red-500' : 'text-gray-500'
                        }`
                    }, priceData.trend),
                    React.createElement('p', { className: 'text-sm text-gray-500' }, 
                        `Güven: ${(priceData.confidence * 100).toFixed(1)}%`)
                ),

                // Fiyat Değişimi Kartı
                React.createElement('div', { className: 'bg-white p-6 rounded-lg shadow-lg' },
                    React.createElement('h2', { className: 'text-sm font-medium text-gray-500 mb-2' }, '24s Değişim'),
                    React.createElement('div', { 
                        className: `text-2xl font-bold ${priceData.price_change_24h >= 0 ? 'text-green-500' : 'text-red-500'}` 
                    }, `${priceData.price_change_24h > 0 ? '+' : ''}${priceData.price_change_24h?.toFixed(2)}%`)
                ),

                // Güncel Fiyat Kartı
                React.createElement('div', { className: 'bg-white p-6 rounded-lg shadow-lg' },
                    React.createElement('h2', { className: 'text-sm font-medium text-gray-500 mb-2' }, 'Güncel Fiyat'),
                    React.createElement('div', { className: 'text-2xl font-bold' }, 
                        formatPrice(priceData.current_price))
                )
            ),

            // Teknik Göstergeler
            React.createElement('div', { className: 'bg-white p-6 rounded-lg shadow-lg mb-8' },
                React.createElement('h2', { className: 'text-lg font-semibold mb-4' }, 'Teknik Göstergeler'),
                React.createElement('div', { className: 'grid grid-cols-1 md:grid-cols-3 gap-4' },
                    React.createElement('div', {},
                        React.createElement('p', { className: 'text-sm text-gray-500' }, 'RSI'),
                        React.createElement('p', { className: 'text-xl font-bold' }, 
                            `${priceData.rsi?.toFixed(2) || 'N/A'}`)
                    ),
                    React.createElement('div', {},
                        React.createElement('p', { className: 'text-sm text-gray-500' }, 'Veri Noktaları'),
                        React.createElement('p', { className: 'text-xl font-bold' }, 
                            priceData.data_points || 'N/A')
                    ),
                    React.createElement('div', {},
                        React.createElement('p', { className: 'text-sm text-gray-500' }, 'Son Güncelleme'),
                        React.createElement('p', { className: 'text-sm' }, 
                            new Date(priceData.last_update).toLocaleString())
                    )
                )
            ),

            // Debug Bilgisi
            isDevelopment && React.createElement('pre', { 
                className: 'bg-white p-4 rounded-lg shadow-lg mt-8 overflow-auto' 
            }, JSON.stringify(priceData, null, 2))
        )
    );
}

// Root element'e render et
ReactDOM.render(
    React.createElement(CryptoDashboard),
    document.getElementById('root')
);