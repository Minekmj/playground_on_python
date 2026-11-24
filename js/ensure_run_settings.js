const rs = document.querySelector('ms-run-settings');
if (!rs) return false;
const rect = rs.getBoundingClientRect();
return rs.classList.contains('expanded') && rect.width > 50 && rect.height > 50;
