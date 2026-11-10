require('dotenv').config();
const express = require('express');
const cors = require('cors');
const crypto = require('crypto');
const nodemailer = require('nodemailer');
const Database = require('better-sqlite3');
const bcrypt = require('bcryptjs');

const app = express();
app.use(cors());
app.use(express.json());

// ====== CHANGE THIS to your SQLite file path ======
const db = new Database('your-database.db');
// Assumes a table: users (email, password)

// Gmail SMTP (uses an App Password, not your real password)
const transporter = nodemailer.createTransport({
  service: 'gmail',
  auth: {
    user: process.env.GMAIL_USER,
    pass: process.env.GMAIL_APP_PASSWORD,
  },
});

// In-memory OTP store: email -> { otp, expires, attempts }
const otps = new Map();
const OTP_TTL_MS = 5 * 60 * 1000;
const MAX_ATTEMPTS = 5;

// 1) Send OTP
app.post('/send-otp', async (req, res) => {
  const { email } = req.body;
  if (!email) return res.status(400).json({ error: 'Email is required' });

  const genericReply = { message: 'If the email exists, an OTP has been sent.' };

  const user = db.prepare('SELECT 1 FROM users WHERE email = ?').get(email);
  if (!user) return res.json(genericReply);

  const otp = String(crypto.randomInt(100000, 1000000));
  otps.set(email, { otp, expires: Date.now() + OTP_TTL_MS, attempts: 0 });

  try {
    await transporter.sendMail({
      from: `"Brewskers Pet Coffee Shop" <${process.env.GMAIL_USER}>`,
      to: email,
      subject: 'Your Brewskers password reset code',
      text: `Your Brewskers Pet Coffee Shop OTP is ${otp}. It expires in 5 minutes. If you didn't request this, ignore this email.`,
    });
    res.json(genericReply);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to send email' });
  }
});

// 2) Verify OTP and reset password
app.post('/reset-password', (req, res) => {
  const { email, otp, newPassword } = req.body;
  if (!email || !otp || !newPassword) {
    return res.status(400).json({ error: 'Email, OTP, and new password are required' });
  }

  const record = otps.get(email);
  if (!record || Date.now() > record.expires) {
    otps.delete(email);
    return res.status(400).json({ error: 'OTP expired or not found' });
  }
  if (++record.attempts > MAX_ATTEMPTS) {
    otps.delete(email);
    return res.status(429).json({ error: 'Too many attempts' });
  }
  if (record.otp !== String(otp)) {
    return res.status(400).json({ error: 'Invalid OTP' });
  }

  const hash = bcrypt.hashSync(newPassword, 10);
  db.prepare('UPDATE users SET password = ? WHERE email = ?').run(hash, email);
  otps.delete(email);
  res.json({ message: 'Password reset successful' });
});

app.listen(3000, () => console.log('Brewskers server running on http://localhost:3000'));