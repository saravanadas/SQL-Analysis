import pandas as pd

def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans and validates data before loading
    """

    # Remove empty rows
    df = df.dropna(how="all")

    # Trim column names
    df.columns = [col.strip() for col in df.columns]

    # Remove duplicates
    df = df.drop_duplicates()

    return df
