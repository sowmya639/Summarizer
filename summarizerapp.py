from string import punctuation
from flask import Flask, render_template, request, redirect, url_for, session, flash
import nltk
from nltk.tokenize import sent_tokenize
from nltk.corpus import stopwords
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import heapq
from PyPDF2 import PdfReader
import re
import io
import os
from sqlalchemy.orm import relationship
from flask_sqlalchemy import SQLAlchemy
import hashlib
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

app.secret_key = 'your_secret_key'
app.config['SQLALCHEMY_BINDS'] = {
    'metadata': 'sqlite:///metadata.db',
    'filevault': 'sqlite:///file_vault.db'
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define the Users model
class Users(db.Model):
    __tablename__ = 'users'
    __bind_key__ = 'metadata'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255))
    password = db.Column(db.String(255))
    email = db.Column(db.String(255))
    files = relationship('Files', backref='user', lazy=True)
    
    def __init__(self, username, password, email):
        self.username = username
        self.password = password
        self.email = email

# Define Files model
class Files(db.Model):
    __bind_key__ = 'metadata'
    __tablename__ = 'files'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255))
    hashkey = db.Column(db.String(64))
    summary = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    def __init__(self, filename, hashkey, summary, user_id):
        self.filename = filename
        self.hashkey = hashkey
        self.summary = summary
        self.user_id = user_id

# Define the FileVault model
class FileVault(db.Model):
    __bind_key__ = 'filevault'
    id = db.Column(db.Integer, primary_key=True)
    hash_name = db.Column(db.String(255))
    asquii_value = db.Column(db.String(64))
    file_data = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    def __repr__(self):
        return f"FileVault(id={self.id}, hash_name={self.hash_name}, asquii_value={self.asquii_value}, file_data={self.file_data})"

# Function to generate hash key
def generate_hash_key(file_content):
    hash_object = hashlib.sha256(file_content)
    return hash_object.hexdigest()

# Function to generate ASCII values
def generate_ascii_values(filename):
    ascii_values = hashlib.sha256(filename.encode()).hexdigest()
    return ascii_values

# Function to extract text from a PDF file with error handling
def extract_text_from_pdf(file_content):
    try:
        pdf_text = ""
        pdf_reader = PdfReader(io.BytesIO(file_content))
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                pdf_text += page_text
        return pdf_text
    except Exception as e:
        print(f"An error occurred while extracting text from the PDF file: {e}")
        return None

# Function to preprocess text
def preprocess_text(text):
    nltk.download('punkt')
    nltk.download('stopwords')
    sentences = sent_tokenize(text)
    processed_sentences = []
    stop_words = set(stopwords.words('english'))
    for sentence in sentences:
        words = [word.lower() for word in nltk.word_tokenize(sentence) if word.lower() not in stop_words and word not in punctuation]
        processed_sentences.append(' '.join(words))
    return processed_sentences

# Function to generate summary using TF-IDF and TextRank
def tfidf_text_rank(text, n=3):
    sentences = preprocess_text(text)
    tfidf_vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = tfidf_vectorizer.fit_transform(sentences)
    sentence_scores = {}
    for i, sentence in enumerate(sentences):
        sentence_scores[sentence] = tfidf_matrix[i].sum()

    # Get the top sentences based on TF-IDF scores
    top_sentences = heapq.nlargest(n, sentence_scores, key=sentence_scores.get)

    # Join the top sentences to form the summary
    summary = ' '.join(top_sentences)
    # Add key sections and evidence to the summary
    mentioned_sections = identify_mentioned_sections(text)
    evidence = extract_evidence(text, "client")
    evidence_summary = ". ".join([f"{cat}: {details['context']} ({details['relevance']})" for cat, details in evidence.items()])

    informative_summary = f"Summary: {summary}\n\nKey Sections: {', '.join(mentioned_sections)}\n\nEvidence: {evidence_summary}"
    return informative_summary

# Function to identify mentioned sections
def identify_mentioned_sections(text, section_pattern=r'Section \d+'):
    mentioned_sections = set(re.findall(section_pattern, text))
    return mentioned_sections

# Function to extract evidence from the text
def extract_evidence(text, client_name):
    evidence_types = {
        "testimonial": {"keywords": ["witness", "testimony", "statement"], "description": "Evidence based on witness accounts."},
        "documentary": {"keywords": ["document", "contract", "email", "letter", "report"], "description": "Evidence provided in documents."},
        "demonstrative": {"keywords": ["diagram", "chart", "photograph", "video"], "description": "Evidence presented visually."},
        "real": {"keywords": ["weapon", "blood", "dna", "forensic"], "description": "Physical evidence."},
        "circumstantial": {"keywords": ["pattern", "behavior", "timeline"], "description": "Inferred evidence based on circumstances."}
    }

    sentences = sent_tokenize(text)
    extracted_evidence = {}

    for sentence in sentences:
        words = nltk.word_tokenize(sentence.lower())
        for category, details in evidence_types.items():
            if any(keyword in words for keyword in details["keywords"]):
                if category not in extracted_evidence:
                    extracted_evidence[category] = {"context": sentence, "occurrences": 1}
                else:
                    extracted_evidence[category]["occurrences"] += 1

    for category, details in extracted_evidence.items():
        if client_name.lower() in details["context"].lower():
            extracted_evidence[category]["relevance"] = "For"
        else:
            extracted_evidence[category]["relevance"] = "Against"

    return extracted_evidence

# Function to calculate cosine similarity
def calculate_cosine_similarity(file_content, summary):
    sentences = sent_tokenize(file_content)
    summary_sentences = sent_tokenize(summary)

    # Combine sentences for both file content and summary
    all_sentences = sentences + summary_sentences

    # Calculate TF-IDF for all sentences
    tfidf_vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = tfidf_vectorizer.fit_transform(all_sentences)

    # Calculate cosine similarity between file content and summary
    cosine_sim = cosine_similarity(tfidf_matrix[:-len(summary_sentences)], tfidf_matrix[-len(summary_sentences):])

    return cosine_sim.max()

# Function to calculate similarity percentage
def calculate_similarity_percentage(similarity_score):
    return round(similarity_score * 100, 2)

@app.route('/')
def welcome():
    return render_template('welcome.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        print("User already logged in, redirecting to index.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        print(f"Received login data: username={username}")

        user = Users.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['username'] = username
            session['user_id'] = user.id
            print("Login successful, redirecting to index.")
            return redirect(url_for('index'))
        else:
            print("Invalid username or password")
            flash('Invalid username or password', 'error')
            return render_template('login.html', error='Invalid username or password')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        
        print(f"Received registration data: username={username}, email={email}")

        existing_user = Users.query.filter((Users.username == username) | (Users.email == email)).first()

        if existing_user:
            if existing_user.username == username:
                flash('Username already exists', 'error')
            elif existing_user.email == email:
                flash('Email already exists', 'error')
            return render_template('register.html', error='Username or Email already exists')
        else:
            hashed_password = generate_password_hash(password, method='sha256')
            new_user = Users(username=username, password=hashed_password, email=email)
            db.session.add(new_user)
            db.session.commit()
            print("New user registered successfully")
            return redirect(url_for('login'))

    return render_template('register.html', error=None)

@app.route('/index', methods=['GET', 'POST'])
def index():
    if 'username' in session:
        if request.method == 'POST' and 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                try:
                    file_content = file.read()
                    ascii_values = generate_ascii_values(file.filename)
                    app.logger.info(f"Generated ASCII values for filename {file.filename}: {ascii_values}")

                    hash_key = generate_hash_key(file_content)
                    app.logger.info(f"Generated hash key for file {file.filename}: {hash_key}")

                    user_id = session['user_id']
                    app.logger.info(f"Retrieved user ID from session: {user_id}")

                    pdf_text = extract_text_from_pdf(file_content)
                    summary = tfidf_text_rank(pdf_text)
                    app.logger.info(f"Generated summary for file {file.filename}: {summary}")

                    file_entry = Files(filename=file.filename, hashkey=hash_key, summary=summary, user_id=user_id)
                    db.session.add(file_entry)
                    db.session.commit()
                    app.logger.info(f"Metadata stored in database for file {file.filename}")

                    hash_filename = f"{file.filename.split('.')[0]}_{hash_key}.{file.filename.split('.')[-1]}"
                    file_vault_entry = FileVault(hash_name=hash_filename, asquii_value=ascii_values, file_data=summary, user_id=user_id)
                    db.session.add(file_vault_entry)
                    db.session.commit()
                    app.logger.info(f"File vault entry created for file {file.filename}")

                    # Calculate cosine similarity
                    cosine_similarity_score = calculate_cosine_similarity(pdf_text, summary)
                    similarity_percentage = calculate_similarity_percentage(cosine_similarity_score)
                    app.logger.info(f"Cosine similarity calculated for file {file.filename}: {cosine_similarity_score}")

                except Exception as e:
                    flash('An error occurred: ' + str(e), 'error')
                    app.logger.error(f"Error occurred while processing file {file.filename}: {e}")

                return redirect(url_for('index'))
            else:
                flash('No file selected', 'error')

        return render_template('index.html', username=session['username'])
    else:
        return redirect(url_for('login'))

@app.route('/display_data')
def display_data():
    stored_data = FileVault.query.all()
    return render_template('display_data.html', stored_data=stored_data)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/summarize', methods=['GET', 'POST'])
def summarize():
    if 'username' in session:
        if request.method == 'POST':
            uploaded_files = request.files.getlist('file')

            results = []

            for file in uploaded_files:
                result = {}

                file_content = file.read()
                pdf_text = extract_text_from_pdf(file_content)
                if pdf_text is not None:
                    mentioned_sections = identify_mentioned_sections(pdf_text)
                    evidence = extract_evidence(pdf_text, "client")

                    summary = tfidf_text_rank(pdf_text)

                    hash_key = generate_hash_key(file_content)
                    ascii_values = generate_ascii_values(file.filename)

                    file_entry = Files(filename=file.filename, hashkey=hash_key, summary=summary, user_id=session.get('user_id'))
                    db.session.add(file_entry)
                    db.session.commit()

                    file_vault_entry = FileVault(hash_name=file.filename, asquii_value=ascii_values, file_data=summary, user_id=session.get('user_id'))
                    db.session.add(file_vault_entry)
                    db.session.commit()

                    # Calculate cosine similarity
                    cosine_similarity_score = calculate_cosine_similarity(pdf_text, summary)
                    similarity_percentage = calculate_similarity_percentage(cosine_similarity_score)

                    result['filename'] = file.filename
                    result['summary'] = summary
                    result['mentioned_sections'] = mentioned_sections
                    result['evidence'] = evidence
                    result['cosine_similarity'] = cosine_similarity_score
                    result['similarity_percentage'] = similarity_percentage

                    results.append(result)

                    # Flash message based on accuracy
                    if cosine_similarity_score >= 0.8:
                        flash(f'Summary generated and stored for {file.filename}. The summary is highly accurate. Similarity: {similarity_percentage}%', 'success')
                    else:
                        flash(f'Summary generated and stored for {file.filename}. The summary is not highly accurate. Similarity: {similarity_percentage}%', 'warning')

            return render_template('summary.html', results=results)
        return redirect(url_for('index'))
    else:
        return redirect(url_for('login'))

if __name__ == '__main__':
    db.create_all(bind='metadata')
    db.create_all(bind='filevault')
    app.run(debug=True)
