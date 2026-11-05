import express from 'express';
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import dotenv from 'dotenv';
import { pool, initDb } from './db.js';

dotenv.config();

const app = express();
app.use(express.json());

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-key-notes';
const PORT = process.env.PORT || 3001;

function authenticate(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Missing or invalid token' });
  }

  const token = authHeader.split(' ')[1];
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = decoded;
    next();
  } catch {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }
}

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.post('/login', async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password required' });
  }

  try {
    const { rows } = await pool.query('SELECT * FROM users WHERE email = $1', [email]);
    if (rows.length === 0) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const user = rows[0];
    const valid = await bcrypt.compare(password, user.password_hash);
    if (!valid) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const token = jwt.sign(
      { userId: user.id, email: user.email },
      JWT_SECRET,
      { expiresIn: '24h' }
    );

    return res.json({ token, user: { id: user.id, email: user.email } });
  } catch (err) {
    console.error('Login error:', err);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

app.post('/notes', authenticate, async (req, res) => {
  const { title, content } = req.body;
  if (!title) {
    return res.status(400).json({ error: 'Title is required' });
  }

  try {
    const { rows } = await pool.query(
      'INSERT INTO notes (user_id, title, content) VALUES ($1, $2, $3) RETURNING id, user_id, title, content, created_at',
      [req.user.userId, title, content || '']
    );
    return res.status(201).json(rows[0]);
  } catch (err) {
    console.error('Create note error:', err);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

app.get('/notes', authenticate, async (req, res) => {
  try {
    const { rows } = await pool.query(
      'SELECT id, user_id, title, content, created_at FROM notes WHERE user_id = $1 ORDER BY created_at DESC',
      [req.user.userId]
    );
    return res.json(rows);
  } catch (err) {
    console.error('List notes error:', err);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

app.get('/notes/:id', authenticate, async (req, res) => {
  const noteId = parseInt(req.params.id, 10);
  if (isNaN(noteId)) {
    return res.status(400).json({ error: 'Invalid note ID' });
  }

  try {
    const { rows } = await pool.query(
      'SELECT id, user_id, title, content, created_at FROM notes WHERE id = $1',
      [noteId]
    );

    if (rows.length === 0) {
      return res.status(404).json({ error: 'Note not found' });
    }

    const note = rows[0];
    if (note.user_id !== req.user.userId) {
      return res.status(403).json({ error: 'Access denied: note belongs to another user' });
    }

    return res.json(note);
  } catch (err) {
    console.error('Get note error:', err);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

app.put('/notes/:id', authenticate, async (req, res) => {
  const noteId = parseInt(req.params.id, 10);
  if (isNaN(noteId)) {
    return res.status(400).json({ error: 'Invalid note ID' });
  }

  try {
    const { rows: existing } = await pool.query(
      'SELECT id, user_id FROM notes WHERE id = $1',
      [noteId]
    );

    if (existing.length === 0) {
      return res.status(404).json({ error: 'Note not found' });
    }

    if (existing[0].user_id !== req.user.userId) {
      return res.status(403).json({ error: 'Access denied: note belongs to another user' });
    }

    const { title, content } = req.body;
    const { rows } = await pool.query(
      'UPDATE notes SET title = COALESCE($1, title), content = COALESCE($2, content) WHERE id = $3 RETURNING id, user_id, title, content, created_at',
      [title, content, noteId]
    );

    return res.json(rows[0]);
  } catch (err) {
    console.error('Update note error:', err);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

app.delete('/notes/:id', authenticate, async (req, res) => {
  const noteId = parseInt(req.params.id, 10);
  if (isNaN(noteId)) {
    return res.status(400).json({ error: 'Invalid note ID' });
  }

  try {
    const { rows: existing } = await pool.query(
      'SELECT id, user_id FROM notes WHERE id = $1',
      [noteId]
    );

    if (existing.length === 0) {
      return res.status(404).json({ error: 'Note not found' });
    }

    if (existing[0].user_id !== req.user.userId) {
      return res.status(403).json({ error: 'Access denied: note belongs to another user' });
    }

    await pool.query('DELETE FROM notes WHERE id = $1', [noteId]);
    return res.json({ message: 'Note deleted successfully' });
  } catch (err) {
    console.error('Delete note error:', err);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

export async function startServer() {
  await initDb();
  return app.listen(PORT, () => {
    console.log(`Notes app listening on http://localhost:${PORT}`);
  });
}

if (process.argv[1] && process.argv[1].endsWith('server.js')) {
  startServer().catch((err) => {
    console.error('Failed to start server:', err);
    process.exit(1);
  });
}
