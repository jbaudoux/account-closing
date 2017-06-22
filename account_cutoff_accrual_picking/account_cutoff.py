# -*- encoding: utf-8 -*-
##############################################################################
#
#    Account Cut-off Accrual Picking module for OpenERP
#    Copyright (C) 2013 Akretion (http://www.akretion.com)
#    @author Alexis de Lattre <alexis.delattre@akretion.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import _, exceptions, models, fields


class account_cutoff(models.Model):
    _inherit = 'account.cutoff'

    def _prepare_lines(self, line, account_mapping):
        """
        Calculate accrued expense using purchase.order.line
        or accrued revenu using sale.order.line
        """

        assert self.type in ('accrued_expense', 'accrued_revenue'),\
            "The field 'type' has a wrong value"
        company_currency_id = self.company_id.currency_id
        if self.type == 'accrued_expense':
            # Processing purchase order line
            # TODO : is this obsolete ?
            account_id = ''  # move_line.product_id.property_account_expense.id
            if not account_id:
                account_id = line.product_id.product_tmpl_id.categ_id.\
                    property_account_expense_categ_id.id
            if not account_id:
                raise exceptions.except_orm(
                    _('Error:'),
                    _("Missing expense account on product '%s' or on its "
                        "related product category.")
                    % (line.product_id.name))
            currency = line.currency_id
            analytic_account_id = line.account_analytic_id.id or False
            # TODO price_unit or price_unit base ?
            price_unit = line.price_unit
            # TODO taxes is it ok ?
            # taxes = move_line.purchase_line_id.taxes_id
            taxes = line.taxes_id
            partner_id = line.order_id.partner_id.id
            tax_account_field_name = 'account_accrued_expense_id'
            tax_account_field_label = 'Accrued Expense Tax Account'
            quantity = line.qty_received - line.qty_invoiced

        elif self.type == 'accrued_revenue':
            # Processing sale order line
            account_id = ''  # line.product_id.property_account_income.id
            if not account_id:
                account_id = line.product_id.product_tmpl_id.categ_id.\
                    property_account_income_categ_id.id
            if not account_id:
                raise exceptions.except_orm(_('Error:'),
                    _("Missing income account on product '%s' or on its "
                        "related product category.")
                    % (line.product_id.name))
            currency = line.currency_id
            analytic_account_id = line.order_id.project_id.id or False
            price_unit = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.tax_id
            partner_id = line.order_id.partner_id.id
            tax_account_field_name = 'account_accrued_revenue_id'
            tax_account_field_label = 'Accrued Revenue Tax Account'
            quantity = line.qty_to_invoice

        currency_id = currency.id
        # TODO Compute total without taxes ?
        tax_line_ids = []
        tax_res = self.env['account.tax'].compute_all(price_unit, None,
            quantity, line.product_id.id, partner_id)
        amount = tax_res['total_excluded']  # =total without taxes
        if self.type == 'accrued_expense':
            amount = amount * -1
        for tax_line in tax_res['taxes']:
            tax_read = self.env['account_tax'].read(
                    [tax_account_field_name, 'name'])
            tax_accrual_account_id = tax_read[tax_account_field_name]
            if not tax_accrual_account_id:
                raise exceptions.except_orm(
                    _('Error:'),
                    _("Missing '%s' on tax '%s'.")
                    % (tax_account_field_label, tax_read['name']))
            else:
                tax_accrual_account_id = tax_accrual_account_id[0]
            if self.type == 'accrued_expense':
                tax_line['amount'] = tax_line['amount'] * -1
            if company_currency_id != currency_id:
                tax_accrual_amount = self.env['res.currency'].with_context(
                    date=self.cutoff_date)._compute(currency_id,
                    company_currency_id, tax_line['amount'])
            else:
                tax_accrual_amount = tax_line['amount']
            tax_line_ids.append((0, 0, {
                'tax_id': tax_line['id'],
                'base': self.env['res.currency'].round(currency,
                    tax_line['price_unit'] * quantity),
                'amount': tax_line['amount'],
                'sequence': tax_line['sequence'],
                'cutoff_account_id': tax_accrual_account_id,
                'cutoff_amount': tax_accrual_amount,
                'analytic_account_id':
                tax_line['account_analytic_collected_id'],
                # account_analytic_collected_id is for
                # invoices IN and OUT
            }))

        if company_currency_id != currency_id:
            amount_company_currency = self.env['res.currency'].with_context(
                date=self.cutoff_date)._compute(
                    currency, company_currency_id, amount)
        else:
            amount_company_currency = amount
        # we use account mapping here
        if account_id in account_mapping:
            accrual_account_id = account_mapping[account_id]
        else:
            accrual_account_id = account_id
        res = {
            'parent_id': self.id,
            'partner_id': partner_id,
            'stock_move_id': line.id,
            'name': line.name,
            'account_id': account_id,
            'cutoff_account_id': accrual_account_id,
            'analytic_account_id': analytic_account_id,
            'currency_id': currency_id,
            'quantity': quantity,
            'price_unit': price_unit,
            'tax_ids': [(6, 0, [tax.id for tax in taxes])],
            'amount': amount,
            'cutoff_amount': amount_company_currency,
            'tax_line_ids': tax_line_ids,
        }
        return res

    def get_lines_for_cutoff(self):
        """ Get purchase or sale order line to generate cutoff"""
        # Delete existing cutoff lines from previous run
        to_delete_line_ids = self.env['account.cutoff.line'].search([
            ('parent_id', '=', self.id),
            ('stock_move_id', '!=', False)])
        if to_delete_line_ids:
            to_delete_line_ids.unlink()
        # Get lines to process
        if self.type == 'accrued_revenue':
            lines = self.env['sale.order.line'].search([
                ['qty_to_invoice', '>', 0],
                # TODO For the date ?
            ])
        elif self.type == 'accrued_expense':
            lines = self.env['purchase.order.line'].search([
                # TODO which qty ? and add dates
                # ['qty_invoiced', '<', 'qty_received'],
                ['qty_received', '>', 0]
                # only purchase not finished
                ])
        # Create account mapping dict
        account_mapping = self.env['account.cutoff.mapping']._get_mapping_dict(
                self.company_id.id, self.type)
        for line in lines:
            if (self.type == 'accrued_expense'):
                if (line.qty_invoiced == line.qty_received):
                    # Process only pol wich are not fully invoiced
                    continue
            print line
            self.env['account.cutoff.line'].create(
                self._prepare_lines(line, account_mapping))
        return True


class account_cutoff_line(models.Model):
    _inherit = 'account.cutoff.line'

    stock_move_id = fields.Many2one(
        comodel_name='stock.move',
        string='Stock Move',
        readonly=True
    )
    product_id = fields.Many2one(
       related='stock_move_id.product_id',
       string='Product',
       readonly=True
    )
    picking_id = fields.Many2one(
        related='stock_move_id.picking_id',
        string='Picking',
        readonly=True
    )
    picking_date_done = fields.Datetime(
        related='picking_id.date_done',
        string='Date Done of the Picking',
        readonly=True
    )
