import bcrypt from 'bcryptjs';
import { pool, initDb } from './db.js';

export async function seed() {
  await initDb();

  const salt = await bcrypt.genSalt(10);
  const hashA = await bcrypt.hash('PasswordA123!', salt);
  const hashB = await bcrypt.hash('PasswordB123!', salt);

  await pool.query(
    `
    INSERT INTO users (email, password_hash)
    VALUES ($1, $2)
    ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;
  `,
    ['user_a@example.com', hashA]
  );

  await pool.query(
    `
    INSERT INTO users (email, password_hash)
    VALUES ($1, $2)
    ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;
  `,
    ['user_b@example.com', hashB]
  );

  console.log('Seeded users successfully:');
  console.log('  User A: user_a@example.com / PasswordA123!');
  console.log('  User B: user_b@example.com / PasswordB123!');
}

if (process.argv[1] && process.argv[1].endsWith('seed.js')) {
  seed()
    .then(() => pool.end())
    .catch((err) => {
      console.error('Seed error:', err);
      process.exit(1);
    });
}
