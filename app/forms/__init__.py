from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, FloatField, IntegerField, \
    TextAreaField, BooleanField, DateField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, InputRequired, Length, NumberRange, Optional
from app.models import STANDARD_VAT_RATE, ZERO_VAT_RATE


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class RegistrationForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone Number', validators=[Optional(), Length(max=20)])
    role = SelectField('Register As', choices=[('manager', 'Manager'), ('supplier', 'Supplier')])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password')])
    company_name = StringField('Company Name (Suppliers only)', validators=[Optional()])
    region = StringField('Delivery Region (Suppliers only)', validators=[Optional()])
    submit = SubmitField('Register')


class ProductForm(FlaskForm):
    name = StringField('Product Name', validators=[DataRequired()])
    category = StringField('Category', validators=[DataRequired()])
    unit_cost = FloatField('Unit Cost (R)', validators=[DataRequired(), NumberRange(min=0)])
    unit_of_measure = SelectField('Unit of Measure',
                                  choices=[('kg', 'kg'), ('unit', 'unit'), ('litre', 'litre'),
                                           ('bag', 'bag'), ('crate', 'crate')])
    shelf_life_days = IntegerField('Shelf Life (days)', validators=[Optional()])
    vat_rate = SelectField('VAT Treatment', coerce=float, default=STANDARD_VAT_RATE,
                           choices=[(STANDARD_VAT_RATE, 'Standard-rated (15%)'),
                                    (ZERO_VAT_RATE, 'Zero-rated (0%)')])
    available = BooleanField('Available', default=True)
    submit = SubmitField('Save Product')


class PurchaseOrderForm(FlaskForm):
    supplier_id = SelectField('Supplier', coerce=int, validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Create Order')


class OrderLineForm(FlaskForm):
    product_id = SelectField('Product', coerce=int, validators=[DataRequired()])
    quantity = FloatField('Quantity', validators=[DataRequired(), NumberRange(min=0.1)])
    submit = SubmitField('Add Item')


class OrderConfirmForm(FlaskForm):
    delivery_date = DateField('Estimated Delivery Date', validators=[DataRequired()])
    submit = SubmitField('Confirm Order')


class InventoryUpdateForm(FlaskForm):
    qty_on_hand = FloatField('Counted Quantity', validators=[InputRequired(), NumberRange(min=0)])
    reorder_level = FloatField('Reorder Level', validators=[InputRequired(), NumberRange(min=0)])
    submit = SubmitField('Update')


class UsageForm(FlaskForm):
    quantity = FloatField('Quantity Used', validators=[InputRequired(), NumberRange(min=0.001)])
    submit = SubmitField('Record Usage')


class WriteDownForm(FlaskForm):
    batch_id = SelectField('Batch', coerce=int, validators=[DataRequired()])
    quantity = FloatField('Quantity Affected', validators=[InputRequired(), NumberRange(min=0.001)])
    nrv_per_unit = FloatField('NRV per Unit (R)', validators=[InputRequired(), NumberRange(min=0)])
    reason = StringField('Reason', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Post Write-down')


class PaymentForm(FlaskForm):
    method = SelectField('Method', choices=[('EFT', 'EFT'), ('Cash', 'Cash'), ('Card', 'Card')])
    submit = SubmitField('Pay')


class ReportForm(FlaskForm):
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    submit = SubmitField('Generate Report')
