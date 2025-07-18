// const API_URL = '/api';
const API_BASE_URL = 'http://localhost';


async function getCurrentUser() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
            method: 'GET',
            credentials: 'include'
        });
        if (response.ok) return await response.json();
        return null;
    } catch (error) {
        // 비로그인 시 401 오류는 정상적인 흐름이므로, 콘솔에 에러를 찍지 않습니다.
        // console.error("Failed to fetch current user:", error);
        return null;
    }
}

/**
 * 로그인 상태에 따라 네비게이션 바의 UI를 변경하는 함수 (수정됨)
 * @param {object | null} [user] - (선택사항) 미리 가져온 사용자 객체.
 */
async function renderNavbar(user) {
    const authLinks = document.getElementById('auth-links');
    if (!authLinks) return;

    // user 정보가 인자로 넘어오지 않았을 경우에만 API를 호출합니다.
    const currentUser = (user === undefined) ? await getCurrentUser() : user;

    if (currentUser) {
        authLinks.innerHTML = `
            <a href="/profile_edit.html" class="nav-link">프로필 수정</a>
            <span class="navbar-text">환영합니다, ${currentUser.username}님!</span>
            <button id="logout-btn" class="btn">로그아웃</button>`;
        
        document.getElementById('logout-btn').addEventListener('click', async () => {
            await fetch(`${API_BASE_URL}/api/auth/logout`, { 
                method: 'POST',
                credentials: 'include'
             });
            document.cookie = "session_id=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
            window.location.href = '/index.html';
        });
    } else {
        authLinks.innerHTML = `
            <a href="/login.html" class="nav-link">로그인</a>
            <a href="/register.html" class="nav-link">회원가입</a>`;
    }
}