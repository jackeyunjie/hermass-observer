#!/usr/bin/env python3
"""Download daily kline data for A-share stocks.

Usage:
    python3 scripts/data_download/download_daily.py --date 2026-05-20 --stocks A250
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from blackwolf_client import BlackWolfClient, download_all_stocks


def get_stock_list(list_type: str = 'A250') -> list:
    """Get stock list.
    
    Args:
        list_type: 'A250', 'A500', or 'ALL'
    
    Returns:
        List of stock codes
    """
    # TODO: Load from actual stock list file
    # For now, return sample list
    if list_type == 'A250':
        # Load A250 stock list
        pass
    
    # Fallback: download from API
    client = BlackWolfClient()
    stocks = client.download_stock_list()
    return [s['code'] for s in stocks]


def main():
    parser = argparse.ArgumentParser(description='Download daily kline data')
    parser.add_argument('--date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--stocks', default='A250', choices=['A250', 'A500', 'ALL'],
                       help='Stock list to download')
    parser.add_argument('--days', type=int, default=180,
                       help='Days of history to download (default 180)')
    parser.add_argument('--output', default='data/raw',
                       help='Output directory')
    args = parser.parse_args()
    
    # Calculate date range
    end_date = datetime.strptime(args.date, '%Y-%m-%d')
    start_date = end_date - timedelta(days=args.days)
    
    print(f"Downloading {args.stocks} stocks from {start_date.date()} to {end_date.date()}")
    
    # Get stock list
    stock_list = get_stock_list(args.stocks)
    print(f"Total stocks: {len(stock_list)}")
    
    # Download
    client = BlackWolfClient()
    output_dir = Path(args.output)
    
    saved = download_all_stocks(
        client,
        stock_list,
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d'),
        output_dir,
        timeframe='daily'
    )
    
    print(f"\nDownloaded {len(saved)} files to {output_dir}")


if __name__ == '__main__':
    main()
