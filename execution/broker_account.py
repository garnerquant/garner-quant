from pathlib import Path
import pandas as pd

ACCOUNT_FILE = "broker_account.csv"


def load_account():

    if Path(ACCOUNT_FILE).exists():

        account = pd.read_csv(
            ACCOUNT_FILE
        )

        for col in [

            "cash",

            "buying_power",

            "portfolio_value",

            "realised_pnl",

            "unrealised_pnl"

        ]:

            account[col] = (

                account[col]

                .astype(float)

            )

        return account

    account = pd.DataFrame([{

        "cash": 10000.0,

        "buying_power": 10000.0,

        "portfolio_value": 10000.0,

        "realised_pnl": 0.0,

        "unrealised_pnl": 0.0

    }])

    account.to_csv(

        ACCOUNT_FILE,

        index=False

    )

    return account


def save_account(

    account

):

    account.to_csv(

        ACCOUNT_FILE,

        index=False

    )


def update_account(

    account,

    cash,

    positions_value,

    realised_pnl,

    unrealised_pnl

):

    portfolio_value = (

        cash

        +

        positions_value

    )

    account.loc[0, "cash"] = float(cash)

    account.loc[0, "buying_power"] = float(cash)

    account.loc[0, "portfolio_value"] = float(

        portfolio_value

    )

    account.loc[0, "realised_pnl"] = float(

        realised_pnl

    )

    account.loc[0, "unrealised_pnl"] = float(

        unrealised_pnl

    )

    save_account(

        account

    )

    return account


def broker_summary():

    account = load_account()

    return {

        "cash":

        float(

            account.loc[

                0,

                "cash"

            ]

        ),

        "buying_power":

        float(

            account.loc[

                0,

                "buying_power"

            ]

        ),

        "portfolio_value":

        float(

            account.loc[

                0,

                "portfolio_value"

            ]

        ),

        "realised_pnl":

        float(

            account.loc[

                0,

                "realised_pnl"

            ]

        ),

        "unrealised_pnl":

        float(

            account.loc[

                0,

                "unrealised_pnl"

            ]

        )

    }