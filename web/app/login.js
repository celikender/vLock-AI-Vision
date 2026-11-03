'use strict';
// Login and first-time setup. The first account is created on this PC and is an admin.
let setup=false;
const $=id=>document.getElementById(id);
function showError(message){$('login-error').textContent=message;$('login-error').hidden=!message;}
async function post(path,body){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
 const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error||'Request failed.');return data;
}
async function start(){
 try{
  const session=await (await fetch('/api/app/session',{cache:'no-store'})).json();
  if(session.authenticated){location.replace('/');return;}
  setup=session.setup_needed;
  if(setup){$('login-title').textContent='Create the admin account';$('login-help').textContent='No accounts exist yet. This first account is an admin: it manages users, configuration and integrations.';$('confirm-row').hidden=false;$('password').autocomplete='new-password';$('login-button').textContent='Create account';}
 }catch(error){showError('The application is not reachable.');}
}
$('login-form').addEventListener('submit',async event=>{
 event.preventDefault();showError('');
 const username=$('username').value.trim(),password=$('password').value;
 if(setup&&password!==$('confirm').value)return showError('The passwords do not match.');
 $('login-button').disabled=true;
 try{await post(setup?'/api/app/setup':'/api/app/login',{username,password});location.replace('/');}
 catch(error){showError(error.message);$('password').value='';if($('confirm'))$('confirm').value='';}
 finally{$('login-button').disabled=false;}
});
start();
