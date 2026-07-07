import pandas as pd
import sys

sys.stdout.reconfigure(encoding='utf-8')

file_path = "abacavir_line_listing_real.xlsx"
print(f"Reading {file_path} using pandas...")

try:
    # Read the excel file
    # OBIEE exports sometimes have some header rows, let's read the file and inspect
    xl = pd.ExcelFile(file_path)
    print(f"Sheet names: {xl.sheet_names}")
    
    # Load the first sheet
    df = xl.parse(xl.sheet_names[0])
    print(f"DataFrame shape: {df.shape}")
    print("\nDataFrame columns:")
    print(df.columns.tolist())
    
    print("\nFirst 10 rows:")
    print(df.head(10))
    
except Exception as e:
    print(f"Error reading Excel file: {e}")
