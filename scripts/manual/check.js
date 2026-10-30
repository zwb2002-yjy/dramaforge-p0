const http = require('http');

function request(path, method, data, cookies) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: '127.0.0.1',
      port: 4180,
      path: path,
      method: method,
      headers: {
        'Content-Type': 'application/json'
      }
    };
    if (cookies) {
      options.headers['Cookie'] = cookies;
    }
    
    const req = http.request(options, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => resolve({
        status: res.statusCode,
        headers: res.headers,
        body: body
      }));
    });
    req.on('error', reject);
    if (data) req.write(JSON.stringify(data));
    req.end();
  });
}

(async () => {
  console.log('Logging in...');
  const loginRes = await request('/api/v1/auth/login', 'POST', {
    email: 'dramaforge.owner@example.com',
    password: 'professional-proof-password-2026'
  });
  
  console.log('Login Status:', loginRes.status);
  const cookies = loginRes.headers['set-cookie'] ? loginRes.headers['set-cookie'].join('; ') : '';
  
  if (loginRes.status !== 200) {
    console.error('Login Failed:', loginRes.body);
    return;
  }
  
  console.log('Fetching projects...');
  const projRes = await request('/api/v1/projects', 'GET', null, cookies);
  console.log('Projects Status:', projRes.status);
  
  if (projRes.status === 200) {
    const projects = JSON.parse(projRes.body);
    console.log(`Found ${projects.items ? projects.items.length : 0} projects.`);
    if (projects.items && projects.items.length > 0) {
      const p = projects.items[0];
      console.log(`First Project: ${p.id} - ${p.title}`);
      
      console.log('Fetching project details...');
      const pRes = await request(`/api/v1/projects/${p.id}`, 'GET', null, cookies);
      console.log('Project Details Status:', pRes.status);
    }
  } else {
    console.log('Error fetching projects:', projRes.body);
  }
  
  console.log('Fetching available models...');
  const modRes = await request('/api/v1/providers/connections', 'GET', null, cookies);
  console.log('Models Status:', modRes.status);
  if (modRes.status === 200) {
    console.log('Connections:', modRes.body.slice(0, 500));
  } else {
    console.log('Error fetching models:', modRes.body);
  }
})();
