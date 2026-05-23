#!/usr/bin/env python3
"""BlackWolf Data API Client.

Handles downloading A-share kline data from BlackWolf API.
"""

import requests
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta


class BlackWolfClient:
    """Client for BlackWolf data API."""
    
    BASE_URL = "https://api.fxyz.site"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})
    
    def download_daily(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """Download daily kline data.
        
        Args:
            stock_code: Stock code (e.g., '000001.SZ')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
        """
        url = f"{self.BASE_URL}/v1/market/ashare/daily"
        
        params = {
            "code": stock_code,
            "start": start_date,
            "end": end_date
        }
        
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if not data or 'data' not in data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data['data'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        return df
    
    def download_5m(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """Download 5-minute kline data for SR calculation."""
        url = f"{self.BASE_URL}/v1/market/ashare/5m"
        
        params = {
            "code": stock_code,
            "start": start_date,
            "end": end_date
        }
        
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if not data or 'data' not in data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data['data'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        return df
    
    def download_stock_list(self) -> List[Dict]:
        """Download A-share stock list."""
        url = f"{self.BASE_URL}/v1/market/ashare/stocks"
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        return data.get('data', [])


def save_kline_data(
    df: pd.DataFrame,
    output_path: Path,
    stock_code: str,
    timeframe: str
):
    """Save kline data to CSV.
    
    Args:
        df: DataFrame with kline data
        output_path: Output directory
        stock_code: Stock code
        timeframe: 'daily' or '5m'
    """
    output_path.mkdir(parents=True, exist_ok=True)
    
    file_path = output_path / f"{stock_code}_{timeframe}.csv"
    df.to_csv(file_path, index=False, encoding='utf-8-sig')
    
    return file_path


def download_all_stocks(
    client: BlackWolfClient,
    stock_list: List[str],
    start_date: str,
    end_date: str,
    output_dir: Path,
    timeframe: str = 'daily'
) -> List[Path]:
    """Download data for all stocks in list.
    
    Args:
        client: BlackWolfClient instance
        stock_list: List of stock codes
        start_date: Start date
        end_date: End date
        output_dir: Output directory
        timeframe: 'daily' or '5m'
    
    Returns:
        List of saved file paths
    """
    saved_files = []
    
    for i, code in enumerate(stock_list):
        try:
            if timeframe == 'daily':
                df = client.download_daily(code, start_date, end_date)
            else:
                df = client.download_5m(code, start_date, end_date)
            
            if not df.empty:
                file_path = save_kline_data(df, output_dir, code, timeframe)
                saved_files.append(file_path)
            
            if (i + 1) % 100 == 0:
                print(f"  Downloaded {i + 1}/{len(stock_list)} stocks")
        
        except Exception as e:
            print(f"  Error downloading {code}: {e}")
            continue
    
    return saved_files
