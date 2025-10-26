from flask import Flask, render_template, request, redirect, url_for, flash
import io
import csv
import pandas as pd
from services.qualification_service import import_qualifications_from_dataframe
import google.generativeai as genai
from flask import jsonify
import time
from flask import Response
from flask_mail import Mail, Message
from config import Config
from urllib.parse import quote # ★追加: ファイル名エンコード用★
# ▼▼▼ User, AppSettings モデルをインポート ▼▼▼
from models.models import db, Company, Qualification, AdminAgency, QualificationIndustry, User, AppSettings
# ▲▲▲ インポート変更 ▲▲▲
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
import os
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

# Import service functions
from services.qualification_service import (
    get_qualification_status_info,
    create_qualification,
    update_qualification,
    delete_qualification_by_id,
    delete_industry_by_id,
    search_qualifications,
    search_all_qualifications
)

app = Flask(__name__)
app.config.from_object(Config)

mail = Mail(app)
db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "このページにアクセスするにはログインが必要です。"
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

O2_GROUP_NAME = "O2グループ"

# --- 通常ルート ---
@app.route('/')
@login_required
def index():
    companies = Company.query.all()
    company_counts = {}
    for company in companies:
        count = Qualification.query.filter(
            Qualification.company_id == company.id,
            Qualification.application_status == '対応待ち'
        ).count()
        company_counts[company.id] = count
    return render_template('index.html', companies=companies, company_counts=company_counts)

@app.route('/search')
@login_required
def search_page():
    keyword = request.args.get('keyword', None)
    status = request.args.get('status', None)
    qualifications_from_db = search_all_qualifications(keyword, status)
    display_qualifications = []
    today = date.today()
    for q in qualifications_from_db:
        status_text, status_color = get_qualification_status_info(q, today)
        admin_agency_name = q.admin_agency.agency_name if q.admin_agency else "未設定"
        company_name = q.company.company_name if q.company else "会社未設定"
        valid_period_str = "未設定"
        if q.valid_period_start and q.valid_period_end:
            valid_period_str = f"{q.valid_period_start.strftime('%Y/%m/%d')} - {q.valid_period_end.strftime('%Y/%m/%d')}"
        deadline_str = "未設定"
        if q.next_application_deadline:
            deadline_str = q.next_application_deadline.strftime('%Y/%m/%d')
        display_qualifications.append({
            'id': q.id, 'company': q.company, 'company_name': company_name,
            'admin_agency_name': admin_agency_name, 'registration_number': q.registration_number,
            'valid_period': valid_period_str, 'next_application_deadline': deadline_str,
            'application_status': status_text, 'status_color': status_color
        })
    return render_template('search.html', qualifications=display_qualifications)


@app.route('/company/<int:company_id>')
@login_required
def company_qualifications(company_id):
    company = Company.query.get_or_404(company_id)
    keyword = request.args.get('keyword', None)
    status = request.args.get('status', None)
    qualifications = search_qualifications(company_id, keyword, status)
    display_qualifications = []
    today = date.today()
    for q in qualifications:
        status_text, status_color = get_qualification_status_info(q, today)
        admin_agency_name = q.admin_agency.agency_name if q.admin_agency else "未設定"
        display_qualifications.append({
            'id': q.id, 'admin_agency_name': admin_agency_name,
            'registration_number': q.registration_number,
            'valid_period': f"{q.valid_period_start.strftime('%Y/%m/%d')} - {q.valid_period_end.strftime('%Y/%m/%d')}",
            'next_application_deadline': q.next_application_deadline.strftime('%Y/%m/%d'),
            'application_status': status_text, 'status_color': status_color
        })
    company_counts = {}
    count = Qualification.query.filter(
        Qualification.company_id == company.id,
        Qualification.application_status == '対応待ち'
    ).count()
    company_counts[company.id] = count
    return render_template('qualifications.html', company=company, qualifications=display_qualifications, company_counts=company_counts)

# --- 資格関連ルート ---
@app.route('/company/<int:company_id>/new_qualification', methods=['GET', 'POST'])
@login_required
def new_qualification(company_id):
    company = Company.query.get_or_404(company_id)
    if request.method == 'POST':
        form_data = request.form.copy()
        form_data['notification_url'] = request.form.get('notification_url')
        form_data['updated_by'] = current_user.username

        success, result = create_qualification(company_id, form_data)
        if success:
            flash('新しい資格情報を登録しました。', 'success')
            return redirect(url_for('company_qualifications', company_id=company_id))
        else:
            flash(f'登録中にエラーが発生しました: {result}', 'danger')
    admin_agencies = AdminAgency.query.all()
    today = date.today()
    return render_template('new_qualification.html', company=company, admin_agencies=admin_agencies, today=today)


@app.route('/qualification/<int:q_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_qualification(q_id):
    qualification = Qualification.query.get_or_404(q_id)
    company = qualification.company
    if request.method == 'POST':
        form_data = request.form.copy()
        form_data['notification_url'] = request.form.get('notification_url')
        form_data['updated_by'] = current_user.username

        success, result = update_qualification(qualification, form_data)
        if success:
            flash('基本情報を更新しました。', 'success')
        else:
            flash(f'基本情報更新中にエラーが発生しました: {result}', 'danger')
        return redirect(url_for('edit_qualification', q_id=q_id))
    admin_agencies = AdminAgency.query.all()
    today = date.today()
    return render_template('edit_qualification.html',
                           company=company, qualification=qualification,
                           admin_agencies=admin_agencies, today=today)


@app.route('/qualification/<int:q_id>/view')
@login_required
def view_qualification(q_id):
    qualification = Qualification.query.get_or_404(q_id)
    industries = qualification.industries
    logs = [] # Placeholder

    # 事前にステータス情報を計算
    today = date.today()
    status_text, status_color = get_qualification_status_info(qualification, today)

    # 会社オブジェクトを明示的に取得
    company = qualification.company 

    return render_template('qualification_detail.html',
                           qualification=qualification,
                           industries=industries,
                           logs=logs,
                           status_text=status_text,
                           status_color=status_color,
                           today=today,
                           company=company
                           )


@app.route('/qualification/<int:q_id>/delete', methods=['POST'])
@login_required
def delete_qualification(q_id):
    success, result = delete_qualification_by_id(q_id)
    if success:
        flash('資格情報を削除しました。', 'info')
        return redirect(url_for('company_qualifications', company_id=result))
    else:
        flash(f'削除中にエラーが発生しました: {result}', 'danger')
        return redirect(url_for('index'))


@app.route('/qualification/<int:q_id>/add_industry', methods=['POST'])
@login_required
def add_industry(q_id):
    qualification = Qualification.query.get_or_404(q_id)
    try:
        industry_name = request.form.get('industry_name')
        grade = request.form.get('grade')
        industry_notes = request.form.get('industry_notes')
        total_score_str = request.form.get('total_score')
        total_score = int(total_score_str) if total_score_str and total_score_str.isdigit() else None
        rating = request.form.get('rating')
        if not industry_name:
            flash('業種名は必須です。', 'danger')
        else:
            new_industry = QualificationIndustry(
                qualification_id=q_id, industry_name=industry_name, grade=grade,
                industry_notes=industry_notes, total_score=total_score, rating=rating
            )
            db.session.add(new_industry)
            db.session.commit()
            flash('新しい業種を追加しました。', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"業種追加エラー: {e}")
        flash(f'業種追加中にエラーが発生しました: {e}', 'danger')
    return redirect(url_for('edit_qualification', q_id=q_id))


@app.route('/industry/<int:industry_id>/delete', methods=['POST'])
@login_required
def delete_industry(industry_id):
    success, result = delete_industry_by_id(industry_id)
    if success:
        flash('業種を削除しました。', 'info')
        return redirect(url_for('edit_qualification', q_id=result))
    else:
        flash(f'業種削除中にエラーが発生しました: {result}', 'danger')
        return redirect(url_for('index'))

# --- 通知・エクスポート・インポート ---
@app.route('/company/<int:company_id>/test_notification')
@login_required
def test_notification(company_id):
    company = Company.query.get_or_404(company_id)
    admin_email_setting = AppSettings.query.filter_by(setting_key='admin_email').first()
    admin_email = admin_email_setting.setting_value if admin_email_setting else None
    if not admin_email:
        flash('通知先メールアドレスが設定されていません。管理設定から設定してください。', 'danger')
        return redirect(url_for('company_qualifications', company_id=company_id))
    try:
        subject = f"[テスト通知] {company.company_name} - 資格管理アプリ"
        body = (f"{company.company_name} の資格管理ページから、通知テストが実行されました...\n\n(送信元: {app.config.get('MAIL_USERNAME', '未設定')})")
        msg = Message(subject=subject, recipients=[admin_email], body=body)
        mail.send(msg)
        flash(f'{admin_email} 宛にテストメールを送信しました。', 'success')
    except Exception as e:
        print(f"メール送信エラー: {e}")
        flash(f'メール送信中にエラーが発生しました: {e}', 'danger')
    return redirect(url_for('company_qualifications', company_id=company_id))


@app.cli.command("init-db")
def init_db_command():
    print("データベースを初期化しています...")
    db.drop_all()
    db.create_all()
    try:
        c1 = Company(company_name='株式会社小田島組', zip_code='025-0000', address='岩手県花巻市〇〇町1-1', phone_number='0198-00-0001')
        c2 = Company(company_name='株式会社泉工務店', zip_code='024-0000', address='岩手県北上市〇〇町2-2', phone_number='0197-00-0002')
        c3 = Company(company_name='有限会社吉田工務店', zip_code='028-0000', address='岩手県遠野市〇〇町3-3', phone_number='0198-00-0003')
        a1 = AdminAgency(agency_name='国土交通省東北地方建設局')
        a2 = AdminAgency(agency_name='岩手県')
        a3 = AdminAgency(agency_name='（ここに3つ目の行政庁）')
        admin_user = User(username='admin', email='admin@example.com', is_admin=True)
        admin_user.set_password('admin')
        db.session.add_all([c1, c2, c3, a1, a2, a3, admin_user])
        db.session.commit()
        print("データベースを初期化し、テストデータを投入しました。")
        print("管理者ユーザー 'admin' (パスワード 'admin') が作成されました。")
    except Exception as e:
        db.session.rollback()
        print(f"データ投入中にエラーが発生しました: {e}")


# ▼▼▼ 修正: 全ての処理を app_context ブロック内に移動 & ファイル名エンコーディング ▼▼▼
@app.route('/export/csv')
@login_required
def export_csv():
    company_id_str = request.args.get('company_id', None)
    keyword = request.args.get('keyword', None)
    status = request.args.get('status', None)
    
    qualifications_to_export = []
    filename = "export.csv"
    output_data = b''
    mimetype = 'text/csv'
    
    # データベースアクセスが必要な全処理を context 内に移動
    with app.app_context():
        if company_id_str:
            try:
                company_id = int(company_id_str)
                # search_qualifications は db.session を内部で使うため context が必要
                qualifications_to_export = search_qualifications(company_id, keyword, status)
                company = Company.query.get(company_id)
                if company:
                    filename = f"{company.company_name}_qualifications_{date.today().strftime('%Y%m%d')}.csv"
                else:
                    qualifications_to_export = []
            except Exception:
                qualifications_to_export = []
        else:
            try:
                # search_all_qualifications は db.session を内部で使うため context が必要
                qualifications_to_export = search_all_qualifications(keyword, status)
                filename = f"all_qualifications_{date.today().strftime('%Y%m%d')}.csv"
            except Exception:
                qualifications_to_export = []

        si = io.StringIO()
        cw = csv.writer(si, quoting=csv.QUOTE_ALL)
        
        # ヘッダー
        header = ['会社名', '許可行政庁', '登録番号', '有効期間(開始)', '有効期間(満了)', '次期申請期限', '申請状況', 'その他備考', '通知書URL']
        cw.writerow(header)
        
        # データの書き込み (ここで q.company や q.admin_agency に安全にアクセスできる)
        for q in qualifications_to_export:
            row = [
                q.company.company_name if q.company else '', 
                q.admin_agency.agency_name if q.admin_agency else '',
                q.registration_number, 
                q.valid_period_start.strftime('%Y-%m-%d'), 
                q.valid_period_end.strftime('%Y-%m-%d'),
                q.next_application_deadline.strftime('%Y-%m-%d'), 
                q.application_status, 
                q.other_notes if q.other_notes else '',
                q.notification_url if q.notification_url else ''
            ]
            cw.writerow(row)
        
        # CSVデータ生成
        try:
            output_data = si.getvalue().encode('cp932')
            mimetype = 'text/csv'
        except UnicodeEncodeError:
            output_data = si.getvalue().encode('utf-8')
            output_data = b'\xef\xbb\xbf' + output_data
            mimetype = 'text/csv; charset=utf-8'
            
    # 応答生成（contextの外側で良い）
    try:
        # ファイル名をURLエンコードし、ASCII文字のみにする
        encoded_filename = quote(filename)
        # Content-Dispositionヘッダーのファイル名を修正 (RFC 6266準拠)
        response = Response(output_data, mimetype=mimetype, headers={
            'Content-Disposition': f'attachment;filename*=UTF-8\'\'{encoded_filename}'
        })
    except Exception:
        # エンコーディングに失敗した場合は、日本語を避けたシンプルな名前でフォールバック
        encoded_filename = "qualifications_export.csv"
        response = Response(output_data, mimetype=mimetype, headers={
            'Content-Disposition': f'attachment;filename="{encoded_filename}"'
        })
        
    return response
# ▲▲▲ 修正完了 ▲▲▲


@app.route('/import/csv/<int:company_id>', methods=['POST'])
@login_required
def import_csv(company_id):
    if 'csv_file' not in request.files:
        flash('ファイルが選択されていません。', 'danger')
        return redirect(url_for('company_qualifications', company_id=company_id))
    file = request.files['csv_file']
    if file.filename == '' or not file.filename.endswith('.csv'):
        flash('CSVファイルを選択してください。', 'danger')
        return redirect(url_for('company_qualifications', company_id=company_id))
    try:
        try:
            file.seek(0)
            df = pd.read_csv(file, dtype=str)
        except UnicodeDecodeError:
            file.seek(0)
            df = pd.read_csv(file, encoding='cp932', dtype=str)
        success_count, errors = import_qualifications_from_dataframe(df, company_id, current_user.username)
        if errors:
            flash(f'{success_count}件のインポートに成功しましたが、以下のエラーが発生しました：', 'warning')
            for error in errors[:5]:
                flash(error, 'danger')
            if len(errors) > 5:
                flash(f'他 {len(errors)-5} 件のエラー...（詳細はログ確認）', 'danger')
        else:
            flash(f'{success_count}件の資格情報をCSVからインポートしました。', 'success')
    except Exception as e:
        flash(f'CSVインポート処理全体でエラーが発生しました: {e}', 'danger')
    return redirect(url_for('company_qualifications', company_id=company_id))


# --- ログイン・管理ルート ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username'); password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user); flash('ログインしました。', 'success'); return redirect(url_for('index'))
        else: flash('ユーザー名またはパスワードが間違っています。', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); flash('ログアウトしました。', 'info'); return redirect(url_for('login'))

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if not current_user.is_admin: flash('管理者権限がありません。', 'danger'); return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username'); email = request.form.get('email')
        password = request.form.get('password'); is_admin = request.form.get('is_admin') == 'on'
        if not username or not password: flash('ユーザー名とパスワードは必須です。', 'danger')
        elif User.query.filter_by(username=username).first(): flash(f'ユーザー名「{username}」は既に使用されています。', 'danger')
        else:
            try:
                new_user = User(username=username, email=email, is_admin=is_admin)
                new_user.set_password(password); db.session.add(new_user); db.session.commit()
                flash(f'新しいユーザー「{username}」を作成しました。', 'success')
            except Exception as e: db.session.rollback(); flash(f'ユーザー作成中にエラーが発生しました: {e}', 'danger')
        return redirect(url_for('admin_users'))
    users = User.query.all(); return render_template('admin_users.html', users=users)

@app.route('/admin/companies', methods=['GET', 'POST'])
@login_required
def admin_companies():
    if not current_user.is_admin: flash('管理者権限がありません。', 'danger'); return redirect(url_for('index'))
    if request.method == 'POST':
        company_name = request.form.get('company_name'); zip_code = request.form.get('zip_code')
        address = request.form.get('address'); phone_number = request.form.get('phone_number')
        if not company_name: flash('会社名は必須です。', 'danger')
        elif Company.query.filter_by(company_name=company_name).first(): flash(f'会社名「{company_name}」は既に使用されています。', 'danger')
        else:
            try:
                new_company = Company(company_name=company_name, zip_code=zip_code, address=address, phone_number=phone_number)
                db.session.add(new_company); db.session.commit()
                flash(f'新しい会社「{company_name}」を作成しました。', 'success')
            except Exception as e: db.session.rollback(); flash(f'会社作成中にエラーが発生しました: {e}', 'danger')
        return redirect(url_for('admin_companies'))
    companies = Company.query.all(); return render_template('admin_companies.html', companies=companies)

@app.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_user_edit(user_id):
    if not current_user.is_admin: flash('管理者権限がありません。', 'danger'); return redirect(url_for('index'))
    user_to_edit = User.query.get_or_404(user_id)
    if request.method == 'POST':
        email = request.form.get('email'); new_password = request.form.get('password')
        is_admin = request.form.get('is_admin') == 'on'
        try:
            user_to_edit.email = email; user_to_edit.is_admin = is_admin
            if new_password: user_to_edit.set_password(new_password)
            db.session.commit(); flash(f'ユーザー「{user_to_edit.username}」の情報を更新しました。', 'success')
        except Exception as e: db.session.rollback(); flash(f'更新中にエラーが発生しました: {e}', 'danger')
        return redirect(url_for('admin_users'))
    return render_template('admin_user_edit.html', user=user_to_edit)

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_user_delete(user_id):
    if not current_user.is_admin: flash('管理者権限がありません。', 'danger'); return redirect(url_for('index'))
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == current_user.id: flash('自分自身のアカウントを削除することはできません。', 'danger'); return redirect(url_for('admin_users'))
    try:
        db.session.delete(user_to_delete); db.session.commit()
        flash(f'ユーザー「{user_to_delete.username}」を削除しました。', 'info')
    except Exception as e: db.session.rollback(); flash(f'削除中にエラーが発生しました: {e}', 'danger')
    return redirect(url_for('admin_users'))

@app.route('/admin/company/<int:company_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_company_edit(company_id):
    if not current_user.is_admin: flash('管理者権限がありません。', 'danger'); return redirect(url_for('index'))
    company_to_edit = Company.query.get_or_404(company_id)
    if request.method == 'POST':
        new_company_name = request.form.get('company_name'); zip_code = request.form.get('zip_code')
        address = request.form.get('address'); phone_number = request.form.get('phone_number')
        if not new_company_name: flash('会社名は必須です。', 'danger')
        elif Company.query.filter(Company.company_name == new_company_name, Company.id != company_id).first(): flash(f'会社名「{new_company_name}」は既に使用されています。', 'danger')
        else:
            try:
                company_to_edit.company_name = new_company_name; company_to_edit.zip_code = zip_code
                company_to_edit.address = address; company_to_edit.phone_number = phone_number
                db.session.commit(); flash(f'会社「{new_company_name}」の情報を更新しました。', 'success')
            except Exception as e: db.session.rollback(); flash(f'更新中にエラーが発生しました: {e}', 'danger')
        return redirect(url_for('admin_companies'))
    return render_template('admin_company_edit.html', company=company_to_edit)

@app.route('/admin/company/<int:company_id>/delete', methods=['POST'])
@login_required
def admin_company_delete(company_id):
    if not current_user.is_admin: flash('管理者権限がありません。', 'danger'); return redirect(url_for('index'))
    company_to_delete = Company.query.get_or_404(company_id); company_name = company_to_edit.company_name
    if Qualification.query.filter_by(company_id=company_id).first(): flash(f'会社「{company_name}」には資格情報が登録されているため、削除できません...', 'danger'); return redirect(url_for('admin_companies'))
    try:
        db.session.delete(company_to_delete); db.session.commit()
        flash(f'会社「{company_name}」を削除しました。', 'info')
    except Exception as e: db.session.rollback(); flash(f'削除中にエラーが発生しました: {e}', 'danger')
    return redirect(url_for('admin_companies'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if not current_user.is_admin: flash('管理者権限がありません。', 'danger'); return redirect(url_for('index'))
    admin_email_setting = AppSettings.query.filter_by(setting_key='admin_email').first()
    if not admin_email_setting:
        admin_email_setting = AppSettings(setting_key='admin_email', setting_value='')
        db.session.add(admin_email_setting)
    if request.method == 'POST':
        new_email = request.form.get('admin_email')
        try:
            admin_email_setting.setting_value = new_email; db.session.commit()
            flash('通知先メールアドレスを更新しました。', 'success')
        except Exception as e: db.session.rollback(); flash(f'更新中にエラーが発生しました: {e}', 'danger')
        return redirect(url_for('admin_settings'))
    return render_template('admin_settings.html', current_email=admin_email_setting.setting_value)


# --- Gemini Q&A ---
@app.route('/qa/ask', methods=['POST'])
@login_required
def ask_qa():
    question = request.json.get('question')
    if not question: return jsonify({'error': '質問がありません。'}), 400
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key: return jsonify({'answer': 'APIキー (GEMINI_API_KEY) が設定されていません。'}), 500
        genai.configure(api_key=api_key); model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = (f"【システム指示】あなたは建設業の資格情報管理アプリケーションのサポートAIです...\n\n【質問】: {question}")
        response = model.generate_content(prompt); answer = response.text
    except Exception as e: print(f"Gemini APIエラー: {e}"); answer = f'APIエラーが発生しました: {e}'
    return jsonify({'answer': answer})

# --- Main execution ---
if __name__ == '__main__':
    if os.path.exists('.env'): from dotenv import load_dotenv; load_dotenv()
    app.run(debug=True)