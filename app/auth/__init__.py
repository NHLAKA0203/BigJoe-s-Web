from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import db, User, Supplier
from app.forms import LoginForm, RegistrationForm

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash(f'Welcome back, {user.name}!', 'success')
            return _redirect_by_role(user.role)
        flash('Invalid email or password.', 'danger')
    return render_template('auth/login.html', form=form)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)
    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html', form=form)
        user = User(
            name=form.name.data,
            email=form.email.data.lower(),
            role=form.role.data,
            phone=form.phone.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        if form.role.data == 'supplier':
            supplier = Supplier(
                user_id=user.id,
                company_name=form.company_name.data or form.name.data,
                region=form.region.data
            )
            db.session.add(supplier)
        db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', form=form)


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.home'))


def _redirect_by_role(role):
    if role == 'manager':
        return redirect(url_for('manager.dashboard'))
    elif role == 'supplier':
        return redirect(url_for('supplier.dashboard'))
    else:
        return redirect(url_for('manager.dashboard'))
