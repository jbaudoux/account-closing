# Account Cutoff Accrual Picking

## Notes about migration to v.10
Historically, this module manages accrued expenses and revenues based on stock-picking.
But following changes up to v.10 in the odoo database schema it can not function as before.

Now instead of basing itself on the stock_picking to generate the calculation, it works directly with sale_order_line and purchase_order_line.

Although a cut-off date can be precised for generating the accruals, it can not work correctly with the module as it is.

## Configuration


## Usage



