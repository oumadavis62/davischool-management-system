@app.get("/", response_class=HTMLResponse)
def home():
    return """
<html><head><meta name='viewport' content='width=device-width, initial-scale=1'></head><body style='font-family:Inter,Arial; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f8fafc; margin:0'>
<div style='background:white; padding:36px 32px; border-radius:16px; border:1px solid #e2e8f0; width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.06)'>
<div style='text-align:center; margin-bottom:28px'>
<div style='width:52px; height:52px; background:#0f172a; color:white; border-radius:14px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:22px; margin:0 auto'>D</div>
<h2 style='margin:14px 0 4px; font-size:22px; font-weight:800; color:#0f172a'>Davischool</h2>
<p style='font-size:12px; color:#64748b; margin:0; letter-spacing:0.3px'>SCHOOL MANAGEMENT SYSTEM</p>
</div>

<form method='post' action='/login'>
<label style='font-size:12px; font-weight:600; color:#334155'>Email</label>
<input name='email' placeholder='Enter your email' required style='width:100%; padding:12px 14px; margin:6px 0 14px; border:1px solid #e2e8f0; border-radius:10px; font-size:13px; outline:none'>
<label style='font-size:12px; font-weight:600; color:#334155'>Password</label>
<input name='password' type='password' placeholder='Enter your password' required style='width:100%; padding:12px 14px; margin:6px 0 20px; border:1px solid #e2e8f0; border-radius:10px; font-size:13px; outline:none'>
<button style='width:100%; background:#0f172a; color:white; padding:12px; border:none; border-radius:10px; font-weight:600; font-size:14px; cursor:pointer'>Sign In</button>
</form>

<div style='margin-top:20px; text-align:center; font-size:11px; color:#94a3b8'>
System auto-detects Super Admin / School
</div>
</div>
</body></html>
"""
