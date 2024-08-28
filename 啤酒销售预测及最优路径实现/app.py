from flask import Flask, render_template, request, send_from_directory
import os
from werkzeug.utils import secure_filename
import pandas as pd
import chardet

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx', 'xls', 'csv'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def clear_uploads_folder():
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        os.unlink(file_path)

def detect_file_encoding(file_path):
    with open(file_path, 'rb') as f:
        raw_data = f.read()
    result = chardet.detect(raw_data)
    return result['encoding']

def read_csv_with_fallback(file_path):
    encodings = ['utf-8', 'gbk', 'gb2312', 'latin1']
    for encoding in encodings:
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError('无法读取CSV文件，尝试的编码均无效')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/uploads', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return '没有文件部分', 400
    file = request.files['file']
    if file.filename == '':
        return '没有选择文件', 400

    filename = secure_filename(file.filename)
    if '.' not in filename:
        return '文件名无效，缺少扩展名', 400

    if allowed_file(filename):
        clear_uploads_folder()
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            file_ext = filename.lower().rsplit('.', 1)[1]
            if file_ext == 'csv':
                try:
                    data = read_csv_with_fallback(file_path)
                except ValueError as e:
                    return f'读取CSV文件时出错: {e}', 500
            else:
                data = pd.read_excel(file_path, engine='openpyxl')

            result_message = f'文件已上传和读取: {filename}'

        except Exception as e:
            return f'读取文件时出错: {e}', 500

        return f'文件已成功上传和读取: {filename}'
    return '上传失败，不支持的文件类型', 400

if __name__ == '__main__':
    app.run(debug=True)
