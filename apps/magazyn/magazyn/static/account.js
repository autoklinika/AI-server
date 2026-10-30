/* Employee/account password management. Same-origin requests use app.js api and CSRF.
   No passwords are stored in browser storage or sent to third-party services. */
document.addEventListener("DOMContentLoaded",()=>{
  const mine=byId("own-password-dialog");
  const mineForm=byId("own-password-form");
  const staff=byId("staff-password-dialog");
  const staffForm=byId("staff-password-form");

  mine.addEventListener("close",()=>mineForm.reset());
  staff.addEventListener("close",()=>{
    staffForm.reset();
    staff.removeAttribute("data-user-id");
  });

  byId("change-own-password").addEventListener("click",()=>{
    if(!session)return;
    mineForm.reset();
    mine.showModal();
    mineForm.elements.current_password.focus();
  });

  mineForm.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!session)return;
    const current=mineForm.elements.current_password.value;
    const replacement=mineForm.elements.new_password.value;
    const repeated=mineForm.elements.confirm_password.value;
    if(replacement!==repeated){
      mineForm.elements.confirm_password.value="";
      toast("Nowe hasła muszą być identyczne.",true);
      return;
    }
    if(replacement===current){
      toast("Wybierz inne hasło niż dotychczasowe.",true);
      return;
    }
    const submit=mineForm.querySelector('button[type="submit"]');
    submit.disabled=true;
    try{
      await api("/api/auth/change-password",{
        method:"POST",
        body:JSON.stringify({current_password:current,new_password:replacement})
      });
      // The backend revoked all sessions and cleared the session cookie.
      showLogin();
      toast("Hasło zostało zmienione. Zaloguj się ponownie.",false);
    }catch(error){
      mineForm.elements.current_password.value="";
      toast(error.message,true);
    }finally{
      submit.disabled=false;
    }
  });

  byId("users-list").addEventListener("click",event=>{
    const button=event.target.closest(".reset-staff-password");
    if(!button||session?.role!=="admin")return;
    const worker=usersCache.find(user=>
      user.id===Number(button.dataset.id)&&user.role==="user");
    if(!worker)return;
    staffForm.reset();
    staff.dataset.userId=String(worker.id);
    byId("staff-password-username").textContent=worker.username;
    staff.showModal();
    staffForm.elements.password.focus();
  });

  staffForm.addEventListener("submit",async event=>{
    event.preventDefault();
    if(session?.role!=="admin")return;
    const workerId=Number(staff.dataset.userId);
    const current=usersCache.find(u=>u.id===workerId&&u.role==="user");
    if(!current){
      toast("Nie znaleziono konta pracownika.",true);
      return;
    }
    const replacement=staffForm.elements.password.value;
    if(replacement!==staffForm.elements.confirm_password.value){
      staffForm.elements.confirm_password.value="";
      toast("Hasła pracownika muszą być identyczne.",true);
      return;
    }
    const submit=staffForm.querySelector('button[type="submit"]');
    submit.disabled=true;
    try{
      await api("/api/users/"+workerId,{
        method:"PATCH",body:JSON.stringify({password:replacement})
      });
      staff.close();
      toast("Hasło pracownika zmienione. Poprzednie sesje wygasły.");
      await loadAdmin();
    }catch(error){
      staffForm.elements.password.value="";
      staffForm.elements.confirm_password.value="";
      toast(error.message,true);
    }finally{
      submit.disabled=false;
    }
  });
});
