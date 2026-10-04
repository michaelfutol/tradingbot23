# PyInstaller spec for TradingBot23
# Build with: pyinstaller tradingbot23.spec

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('.env.example', '.'),
        ('assets/ui', 'assets/ui'),
    ],
    hiddenimports=[
        'bot',
        'bot.config',
        'bot.main',
        'bot.setup_wizard',
        'bot.modules',
        'bot.modules.data_fetcher',
        'bot.modules.futures_trader',
        'bot.bridge_cli',
        'bot.modules.local_bridge',
        'bot.modules.okx_bridge',
        'bot.modules.account_lock',
        'bot.modules.strategy',
        'bot.modules.backtester',
        'bot.modules.event_ledger',
        'binance',
        'binance.client',
        'binance.exceptions',
        'dotenv',
        'requests',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=True,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TradingBot23',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon='assets/tradingbot23.ico',
)
