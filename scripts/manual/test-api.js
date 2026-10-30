const http = require('http');
const req = http.request('http://127.0.0.1:4180/api/v1/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  }
}, (res) => {
  console.log(`Status: ${res.statusCode}`);
  let data = '';
  res.on('data', chunk => data += chunk);
  res.on('end', () => console.log('Response:', data));
});
req.on('error', (e) => console.error(e));
req.write(JSON.stringify({
  email: 'dramaforge.owner@example.com',
  password: 'professional-proof-password-2026'
}));
req.end();
