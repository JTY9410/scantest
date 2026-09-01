<?php

use App\Models\User;
use App\Models\Company;
use App\Models\RefreshToken;
use App\Models\SmsVerification;
use Illuminate\Support\Facades\Hash;
use PHPOpenSourceSaver\JWTAuth\Facades\JWTAuth;
use Carbon\Carbon;
use PHPOpenSourceSaver\JWTAuth\Exceptions\TokenExpiredException;
use Illuminate\Support\Facades\Log;

// 1. 기본 인증/토큰 관련 테스트
test('로그인 및 토큰 발급/조회/무효화 통합 테스트', function () {
    // 1.1 로그인 성공
    $user = User::factory()->create([
        'tid' => 'testuser',
        'password' => 'password123',
    ]);

    $response = $this->postJson('/api/auth/login', [
        'tid' => 'testuser',
        'password' => 'password123',
    ]);

    $response->assertStatus(200)
        ->assertJsonStructure([
            'accessToken',
            'refreshToken',
            'tokenType',
            'expiresIn',
            'user' => [
                'id',
                'companyId',
                'type',
                'mobile',
                'bizNo',
                'tid',
                'name',
                'email',
            ],
        ]);

    $token = $response->json('accessToken');
    $refreshToken = $response->json('refreshToken');

    // 1.2 리프레시 토큰 생성 확인
    $this->assertDatabaseHas('refresh_tokens', [
        'user_id' => $user->id,
    ]);

    // 1.3 사용자 정보 조회
    $meResponse = $this->withHeaders([
        'Authorization' => 'Bearer ' . $token,
    ])->getJson('/api/auth/me');

    $meResponse->assertStatus(200)
        ->assertJson([
            'user' => [
                'id' => $user->id,
                'tid' => $user->tid,
            ]
        ]);

    // 1.4 리프레시 토큰으로 새로운 액세스 토큰 발급
    $refreshResponse = $this->postJson('/api/auth/refresh', [
        'refresh_token' => $refreshToken,
    ]);

    $refreshResponse->assertStatus(200)
        ->assertJsonStructure([
            'accessToken',
            'refreshToken',
            'tokenType',
            'expiresIn',
        ]);

    // 1.5 기존 리프레시 토큰 소프트 삭제 확인
    $this->assertSoftDeleted('refresh_tokens', [
        'token' => $refreshToken,
    ]);

    // 1.6 새로운 리프레시 토큰 생성 확인
    $this->assertDatabaseHas('refresh_tokens', [
        'user_id' => $user->id,
    ]);

    // 1.7 로그아웃
    $logoutResponse = $this->withHeaders([
        'Authorization' => 'Bearer ' . $token,
    ])->postJson('/api/auth/logout', [
        'refresh_token' => $refreshToken,
    ]);

    $logoutResponse->assertStatus(200)
        ->assertJson([
            'message' => '로그아웃되었습니다.',
        ]);

    // 1.8 로그아웃 후 토큰 무효화 확인
    $invalidResponse = $this->withHeaders([
        'Authorization' => 'Bearer ' . $token,
    ])->getJson('/api/auth/me');

    $invalidResponse->assertStatus(401);
});

test('로그인 실패 및 토큰 관련 예외 케이스', function () {
    // 2.1 잘못된 자격증명으로 로그인
    $user = User::factory()->create([
        'password' => Hash::make('password123'),
    ]);

    $response = $this->postJson('/api/auth/login', [
        'tid' => $user->tid,
        'password' => 'wrong-password',
    ]);

    $response->assertStatus(400);

    // 2.2 인증되지 않은 사용자의 정보 조회
    $response = $this->getJson('/api/auth/me');
    $response->assertStatus(401);

    // 2.3 유효하지 않은 리프레시 토큰
    $response = $this->postJson('/api/auth/refresh', [
        'refresh_token' => 'invalid-token',
    ]);

    $response->assertStatus(401)
        ->assertJson([
            'message' => '유효하지 않은 리프레시 토큰입니다.',
        ]);

    // 2.4 리프레시 토큰 없음
    $response = $this->postJson('/api/auth/refresh');
    $response->assertStatus(400);

    // 2.5 잘못된 형식의 토큰
    $response = $this->withHeaders([
        'Authorization' => 'Bearer invalid-token',
    ])->getJson('/api/auth/me');

    $response->assertStatus(401);
});

// 2. SMS 인증 관련 테스트
test('SMS 인증 프로세스 통합 테스트', function () {
    // 2.1 기본 SMS 인증번호 요청
    $response = $this->postJson('/api/auth/requestSms', [
        'mobile' => '01012345678',
        'smsCodeKey' => 'register'
    ]);

    $response->assertStatus(200);

    $this->assertDatabaseHas('sms_verifications', [
        'mobile' => '01012345678',
        'sms_code_key' => 'register',
        'is_verified' => false
    ]);

    // 2.2 tid와 mobile 일치 확인
    $user = User::factory()->create([
        'tid' => 'testuser',
        'mobile' => '01012345678'
    ]);

    // 일치하는 경우
    $response = $this->postJson('/api/auth/requestSms', [
        'tid' => 'testuser',
        'mobile' => '01012345678',
        'smsCodeKey' => 'register'
    ]);

    $response->assertStatus(200);

    // 일치하지 않는 경우
    $response = $this->postJson('/api/auth/requestSms', [
        'tid' => 'testuser',
        'mobile' => '01099999999',
        'smsCodeKey' => 'register'
    ]);

    $response->assertStatus(400);

    // 2.3 SMS 인증번호 확인
    SmsVerification::create([
        'mobile' => '01012345678',
        'sms_code' => '1111',
        'sms_code_key' => 'register',
        'expires_at' => now()->addMinutes(3),
        'is_verified' => false
    ]);

    $response = $this->postJson('/api/auth/verifySms', [
        'mobile' => '01012345678',
        'sms_code' => '1111',
        'smsCodeKey' => 'register'
    ]);

    $response->assertStatus(200);

    $this->assertDatabaseHas('sms_verifications', [
        'mobile' => '01012345678',
        'sms_code' => '1111',
        'sms_code_key' => 'register',
        'is_verified' => true
    ]);

    // 2.4 잘못된 SMS 인증번호
    $response = $this->postJson('/api/auth/verifySms', [
        'mobile' => '01012345678',
        'sms_code' => '9999',
        'smsCodeKey' => 'register'
    ]);

    $response->assertStatus(400);
});

// 3. 회원정보 변경(비밀번호/휴대폰) 관련 테스트
test('회원정보 변경 및 토큰 재발급 통합 테스트', function () {
    $user = User::factory()->create([
        'tid' => 'changepass',
        'mobile' => '01012345678',
        'password' => 'password123'
    ]);

    // 3.1 로그인 및 초기 토큰 획득
    $loginResponse = $this->postJson('/api/auth/login', [
        'tid' => 'changepass',
        'password' => 'password123'
    ]);

    $initialToken = $loginResponse->json('accessToken');

    // 3.2 비밀번호 변경
    $passwordResponse = $this->withHeaders([
        'Authorization' => 'Bearer ' . $initialToken
    ])->postJson('/api/auth/setPassword', [
        'password' => 'password123',
        'newPassword' => 'newpassword123',
        'newPasswordConfirmation' => 'newpassword123'
    ]);

    $passwordResponse->assertStatus(200)
        ->assertJsonStructure([
            'accessToken',
            'refreshToken'
        ]);

    $afterPasswordChangeToken = $passwordResponse->json('accessToken');

    // 3.3 휴대폰 번호 변경
    $newMobile = '01098765432';

    // SMS 인증 요청
    $smsResponse = $this->withHeaders([
        'Authorization' => 'Bearer ' . $afterPasswordChangeToken
    ])->postJson('/api/auth/requestSms', [
        'mobile' => $newMobile,
        'smsCodeKey' => 'change_mobile'
    ]);
    $smsResponse->assertStatus(200);

    // SMS 인증 확인
    $verifyResponse = $this->withHeaders([
        'Authorization' => 'Bearer ' . $afterPasswordChangeToken
    ])->postJson('/api/auth/verifySms', [
        'mobile' => $newMobile,
        'smsCode' => '1111',
        'smsCodeKey' => 'change_mobile'
    ]);
    $verifyResponse->assertStatus(200);

    // 휴대폰 번호 변경
    $mobileResponse = $this->withHeaders([
        'Authorization' => 'Bearer ' . $afterPasswordChangeToken
    ])->postJson('/api/auth/setMobile', [
        'mobile' => $newMobile,
        'smsCode' => '1111',
        'smsCodeKey' => 'change_mobile'
    ]);

    $mobileResponse->assertStatus(200)
        ->assertJsonStructure([
            'accessToken',
            'refreshToken'
        ]);

    $afterMobileChangeToken = $mobileResponse->json('accessToken');

    // 3.4 토큰 무효화 확인
    // 초기 토큰으로 접근 시도 (실패)
    $response = $this->withHeaders([
        'Authorization' => 'Bearer ' . $initialToken
    ])->getJson('/api/auth/me');
    $response->assertStatus(401);

    // 비밀번호 변경 후 토큰으로 접근 시도 (실패)
    $response = $this->withHeaders([
        'Authorization' => 'Bearer ' . $afterPasswordChangeToken
    ])->getJson('/api/auth/me');
    $response->assertStatus(401);

    // 최종 토큰으로 접근 시도 (성공)
    $response = $this->withHeaders([
        'Authorization' => 'Bearer ' . $afterMobileChangeToken
    ])->getJson('/api/auth/me');
    $response->assertStatus(200);

    // 3.5 잘못된 기존 비밀번호로 변경 시도
    $response = $this->withHeaders([
        'Authorization' => 'Bearer ' . $afterMobileChangeToken
    ])->postJson('/api/auth/setPassword', [
        'password' => 'wrongpass123',
        'newPassword' => 'newpassword123',
        'newPasswordConfirmation' => 'newpassword123'
    ]);
    $response->assertStatus(400);
});

// 4. 회원가입/탈퇴 관련 테스트
test('회원가입 및 탈퇴 통합 테스트', function () {
    // 4.1 회원가입
    $company = Company::factory()->create([
        'code' => 'TESTCOMPANY',
        'name' => '테스트 회사',
    ]);

    $userData = [
        'tid' => 'newuser',
        'name' => '새로운 사용자',
        'email' => 'newuser@example.com',
        'password' => 'password123',
        'passwordConfirmation' => 'password123',
        'type' => 'tester',
        'mobile' => '01012345678',
        'companyId' => $company->id,
    ];

    $response = $this->postJson('/api/auth/register', $userData);
    $response->assertStatus(201);

    $this->assertDatabaseHas('users', [
        'tid' => 'newuser',
        'email' => 'newuser@example.com',
        'mobile' => '01012345678',
    ]);

    // 4.2 탈퇴
    $user = User::where('tid', 'newuser')->first();

    // 로그인하여 토큰 획득
    $loginResponse = $this->postJson('/api/auth/login', [
        'tid' => 'newuser',
        'password' => 'password123'
    ]);

    $token = $loginResponse->json('accessToken');

    // 탈퇴 요청
    $response = $this->withHeaders([
        'Authorization' => 'Bearer ' . $token
    ])->postJson('/api/auth/withdraw');

    $response->assertStatus(200);

    // 사용자가 삭제되었는지 확인
    $this->assertSoftDeleted('users', [
        'id' => $user->id
    ]);

    // 탈퇴 후 로그인 시도 (실패)
    $loginResponse = $this->postJson('/api/auth/login', [
        'tid' => 'newuser',
        'password' => 'password123'
    ]);

    $loginResponse->assertStatus(400);

    // 4.3 인증되지 않은 사용자의 탈퇴 시도
    $response = $this->postJson('/api/auth/withdraw');
    $response->assertStatus(401);
});

// 5. 기타 테스트
test('회사 코드 조회 테스트', function () {
    $company = Company::factory()->create([
        'code' => 'TESTCOMPANY',
        'name' => '테스트 회사',
    ]);

    $response = $this->postJson('/api/auth/companyCode', [
        'companyCode' => 'TESTCOMPANY'
    ]);

    $response->assertStatus(200)
        ->assertJson([
            'code' => 'TESTCOMPANY',
            'name' => '테스트 회사'
        ]);

    // 존재하지 않는 회사 코드
    $response = $this->postJson('/api/auth/companyCode', [
        'companyCode' => 'NONEXISTENT'
    ]);

    $response->assertStatus(400);
});

test('JWT 토큰 설정 및 만료 테스트', function () {
    // 시간대를 Asia/Seoul로 설정
    date_default_timezone_set('Asia/Seoul');

    // 현재 시간 저장
    $now = Carbon::now()->startOfSecond();
    Carbon::setTestNow($now);

    // 토큰 만료 시간을 1분으로 설정
    config(['jwt.ttl' => 1]); // 1분
    config(['jwt.blacklist_enabled' => true]);
    config(['jwt.blacklist_grace_period' => 0]);

    $user = User::factory()->create([
        'password' => Hash::make('password123'),
    ]);

    // 토큰 생성
    $token = JWTAuth::fromUser($user);

    // 토큰 페이로드 확인
    $payload = JWTAuth::setToken($token)->getPayload();
    $exp = $payload->get('exp');
    $iat = $payload->get('iat');

    // 만료 시간이 현재 시간 + 1분인지 확인
    expect($exp)->toBe($now->timestamp + 60);
    expect($iat)->toBe($now->timestamp);

    // 토큰이 유효한지 확인 (즉시)
    $response = $this->withHeaders([
        'Authorization' => 'Bearer ' . $token,
    ])->getJson('/api/auth/me');
    $response->assertStatus(200);

    // 시간을 2분 뒤로 이동 (만료 시간을 확실히 넘기도록)
    Carbon::setTestNow($now->copy()->addMinutes(2));

    // 현재 시간이 만료 시간을 지났는지 확인
    expect(Carbon::now()->timestamp)->toBeGreaterThan($exp);

    // 토큰이 만료되었는지 직접 확인
    try {
        JWTAuth::setToken($token)->checkOrFail();
        $this->fail('토큰이 만료되었어야 합니다');
    } catch (TokenExpiredException $e) {
        expect(true)->toBeTrue();
    }

    // 만료된 토큰으로 요청
    $response = $this->withHeaders([
        'Authorization' => 'Bearer ' . $token,
    ])->getJson('/api/auth/me');

    $response->assertStatus(401);

    // 테스트 시간 초기화
    Carbon::setTestNow();
});

test('아이디 찾기(findTid) 테스트', function () {
    $user = User::factory()->create([
        'tid' => 'findtiduser',
        'mobile' => '01011112222',
    ]);

    // 존재하는 휴대폰 번호로 요청
    $response = $this->postJson('/api/auth/findTid', [
        'mobile' => '010-1111-2222',
    ]);
    $response->assertStatus(200)
        ->assertJsonStructure([
            'message',
            'createdAt',
            'maskedTid',
        ]);

    // 존재하지 않는 휴대폰 번호로 요청
    $response = $this->postJson('/api/auth/findTid', [
        'mobile' => '01099998888',
    ]);
    $response->assertStatus(400);
});

test('SMS 인증 후 비밀번호 재설정(setPasswordByVerifySms) 테스트', function () {
    $user = User::factory()->create([
        'tid' => 'pwresetuser',
        'mobile' => '01022223333',
        'password' => 'oldpassword',
    ]);

    // 인증번호 발송 및 인증 처리
    SmsVerification::create([
        'mobile' => '01022223333',
        'sms_code' => '1111',
        'sms_code_key' => 'reset_password',
        'expires_at' => now()->addMinutes(3),
        'is_verified' => true
    ]);

    // 1. 정상 케이스
    $response = $this->postJson('/api/auth/setPasswordByVerifySms', [
        'tid' => 'pwresetuser',
        'mobile' => '01022223333',
        'smsCode' => '1111',
        'smsCodeKey' => 'reset_password',
        'password' => 'newpassword',
        'passwordConfirmation' => 'newpassword',
    ]);
    $response->assertStatus(200)
        ->assertJsonStructure([
            'accessToken', 'refreshToken', 'tokenType', 'expiresIn',
        ]);

    // 2. 인증되지 않은 상태
    SmsVerification::create([
        'mobile' => '01022223333',
        'sms_code' => '2222',
        'sms_code_key' => 'reset_password',
        'expires_at' => now()->addMinutes(3),
        'is_verified' => false
    ]);
    $response = $this->postJson('/api/auth/setPasswordByVerifySms', [
        'tid' => 'pwresetuser',
        'mobile' => '01022223333',
        'smsCode' => '2222',
        'smsCodeKey' => 'reset_password',
        'password' => 'newpassword',
        'passwordConfirmation' => 'newpassword',
    ]);
    $response->assertStatus(400);

    // 3. 비밀번호 불일치
    SmsVerification::create([
        'mobile' => '01022223333',
        'sms_code' => '3333',
        'sms_code_key' => 'reset_password',
        'expires_at' => now()->addMinutes(3),
        'is_verified' => true
    ]);
    $response = $this->postJson('/api/auth/setPasswordByVerifySms', [
        'tid' => 'pwresetuser',
        'mobile' => '01022223333',
        'smsCode' => '3333',
        'smsCodeKey' => 'reset_password',
        'password' => 'newpassword',
        'passwordConfirmation' => 'notmatch',
    ]);
    $response->assertStatus(400);

    // 4. 존재하지 않는 사용자
    $response = $this->postJson('/api/auth/setPasswordByVerifySms', [
        'tid' => 'notexist',
        'mobile' => '01022223333',
        'smsCode' => '3333',
        'smsCodeKey' => 'reset_password',
        'password' => 'newpassword',
        'passwordConfirmation' => 'newpassword',
    ]);
    $response->assertStatus(400);
});

test('회원가입 필드 유효성 검사(registerValidate) 테스트', function () {
    // 1. 아이디 중복
    User::factory()->create(['tid' => 'dupuser']);
    $response = $this->postJson('/api/auth/registerValidate', [
        'tid' => 'dupuser',
    ]);
    $response->assertStatus(422)
        ->assertJsonStructure(['message', 'errors']);

    // 2. 비밀번호 불일치
    $response = $this->postJson('/api/auth/registerValidate', [
        'password' => 'password123',
        'passwordConfirmation' => 'notmatch',
    ]);
    $response->assertStatus(422);

    // 3. 정상 케이스
    $response = $this->postJson('/api/auth/registerValidate', [
        'tid' => 'uniqueuser',
        'password' => 'password123',
        'passwordConfirmation' => 'password123',
    ]);
    $response->assertStatus(200)
        ->assertJson(['message' => '모든 입력값이 유효합니다.']);
});

test('User/SmsVerification 입력값 포맷 관련 테스트', function () {
    // User::setMobileAttribute, formatMobile
    $user = User::factory()->create([
        'mobile' => '010-1234-5678',
        'biz_no' => '123-45-67890',
        'password' => 'password123',
    ]);
    // 저장 시 숫자만 저장되는지
    $this->assertEquals('01012345678', $user->mobile);
    // formatMobile()
    $this->assertEquals('010-1234-5678', $user->formatMobile());
    // setBizNoAttribute/getBizNoAttribute
    $this->assertEquals('1234567890', $user->getAttributes()['biz_no']);
    $this->assertEquals('123-45-67890', $user->biz_no);

    // SmsVerification::setMobileAttribute
    $sms = SmsVerification::create([
        'mobile' => '010 9999-8888',
        'sms_code' => '1111',
        'sms_code_key' => 'test',
        'expires_at' => now()->addMinutes(3),
        'is_verified' => false
    ]);
    $this->assertEquals('01099998888', $sms->mobile);
});
