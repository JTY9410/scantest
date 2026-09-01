<?php

namespace App\Http\Controllers\Auth;

use App\Models\User;
use Illuminate\Support\Str;
use App\Models\RefreshToken;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Log;
use App\Http\Controllers\Controller;
use App\Http\Requests\Auth\LoginRequest;
use App\Http\Requests\Auth\RegisterRequest;
use PHPOpenSourceSaver\JWTAuth\Facades\JWTAuth;
use App\Models\SmsVerification;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Validator;
use Illuminate\Support\Facades\DB;

class AuthController extends Controller
{
    public function login(LoginRequest $request): JsonResponse
    {
        $credentials = $request->only('tid', 'password');

        Log::info('로그인 시도', [
            'tid' => $credentials['tid'],
            'password_length' => strlen($credentials['password'])
        ]);

        if (!$token = JWTAuth::attempt($credentials)) {
            // soft deleted 사용자 체크
            $user = User::withTrashed()->where('tid', $credentials['tid'])->first();
            if ($user && $user->trashed()) {
                return response()->json([
                    'message' => '탈퇴한 사용자입니다.'
                ], 400);
            }
            Log::error('로그인 실패', [
                'tid' => $credentials['tid'],
                'error' => '인증 실패'
            ]);
            return response()->json([
                'message' => '아이디 또는 비밀번호가 일치하지 않습니다.',
            ], 400);
        }

        $user = JWTAuth::user();
        Log::info('로그인 성공', [
            'user_id' => $user->id,
            'tid' => $user->tid
        ]);

        // 리프레시 토큰 생성
        $refreshToken = $this->createRefreshToken($user);

        return response()->json([
            'accessToken' => $token,
            'refreshToken' => $refreshToken->token,
            'tokenType' => 'bearer',
            'expiresIn' => JWTAuth::factory()->getTTL() * 60,
            'user' => $user,
        ]);
    }

    public function logout(): JsonResponse
    {
        $user = auth()->user();
        $token = JWTAuth::getToken();

        // 현재 리프레시 토큰 삭제
        $refreshToken = request()->input('refresh_token');
        if ($refreshToken) {
            RefreshToken::where('token', $refreshToken)
                ->where('user_id', $user->id)
                ->delete();
        }

        // JWT 토큰 무효화
        JWTAuth::invalidate($token);

        return response()->json([
            'message' => '로그아웃되었습니다.',
        ]);
    }

    /**
     * 리프레시 토큰 갱신
     * @LRDparam refresh_token string|required
     * @LRDresponses 200|400|401
     */
    public function refresh(): JsonResponse
    {
        $refreshToken = request()->input('refresh_token');

        if (!$refreshToken) {
            return response()->json([
                'message' => '리프레시 토큰이 필요합니다.',
            ], 400);
        }

        $token = RefreshToken::where('token', $refreshToken)
            ->where('expires_at', '>', now())
            ->first();

        if (!$token) {
            return response()->json([
                'message' => '유효하지 않은 리프레시 토큰입니다.',
            ], 401);
        }

        $user = $token->user;

        // 새로운 액세스 토큰 생성
        $newAccessToken = JWTAuth::fromUser($user);

        // 기존 리프레시 토큰 삭제
        $token->delete();

        // 새로운 리프레시 토큰 생성
        $newRefreshToken = $this->createRefreshToken($user);

        return $this->createTokenResponse($newAccessToken, $newRefreshToken->token);
    }

    public function me(): JsonResponse
    {
        return response()->json(['user' => auth()->user()]);
    }

    /**
     * 모든 토큰을 무효화합니다.
     *
     * @return JsonResponse
     */
    public function invalidateAllTokens(?User $user = null): JsonResponse
    {
        if( !$user ) {
            $user = auth()->user();
        }

        $user->invalidateAllTokens();

        // 새로운 토큰 발급
        $accessToken = JWTAuth::fromUser($user);
        $refreshToken = $this->createRefreshToken($user)->token;

        return $this->createTokenResponse($accessToken, $refreshToken);
    }

    private function createRefreshToken($user): RefreshToken
    {
        return RefreshToken::create([
            'user_id' => $user->id,
            'token' => Str::random(64),
            'expires_at' => now()->addMinutes(config('jwt.refresh_ttl')),
        ]);
    }

    private function createTokenResponse(string $accessToken, string $refreshToken): JsonResponse
    {
        return response()->json([
            'accessToken' => $accessToken,
            'refreshToken' => $refreshToken,
            'tokenType' => 'bearer',
            'expiresIn' => JWTAuth::factory()->getTTL() * 60,
        ]);
    }

    /**
     * 회사 조회
     * @LRDparam company_code string|required
     * @LRDresponses 200|400
     */
    public function companyCode(Request $request): JsonResponse
    {
        $company = \App\Models\Company::where('code', $request->company_code)->first();

        if (!$company) {
            return response()->json([
                'message' => '존재하지 않는 회사입니다'
            ], 400);
        }

        return response()->json($company);
    }

    public function register(RegisterRequest $request): JsonResponse
    {
        DB::transaction(function () use ($request) {
            User::create($request->validated());
        });

        return response()->json([
            'message' => '회원가입이 완료되었습니다.',
        ], 201);
    }

    /**
     * 휴대폰 인증번호 요청
     * @LRDparam mobile string|required
     * @LRDparam sms_code_key string|required 구분코드 (회원가입, 비밀번호 찾기 등) 직접지정
     * @LRDparam tid string|nullable 아이디일치확인
     * @LRDresponses 200|400
     *
     * @lrd:start
     * # 개발 중 임시코드 1111
     * @lrd:end
     *
     */
    public function requestSms(Request $request): JsonResponse
    {
        $tid = $request->input('tid') ?? null;
        $mobile = $request->input('mobile');
        $sms_code_key = $request->input('sms_code_key');

        // TODO: 문자발송 실제
        // $sms = new \App\Services\SmsService();
        // $sms->sendSms($mobile);

        // 임시 코드 생성 (실제로는 SMS로 전송)
        $sms_code = '1111';

        if( $tid ) {
            $user = User::where('tid', $tid)
                ->where('mobile', $mobile)
                ->first();
            if( !$user ) {
                return response()->json([
                    'message' => '아이디와 휴대폰 번호가 일치하지 않습니다'
                ], 400);
            }
        }

        // SMS 인증 정보 저장
        SmsVerification::createVerification(
            $mobile,
            $sms_code,
            $sms_code_key
        );

        return response()->json([
            'message' => '휴대폰 인증번호가 발송되었습니다',
        ], 200);
    }

    /**
     * 휴대폰 인증번호 확인
     * @LRDparam mobile string|required
     * @LRDparam sms_code string|required
     * @LRDparam sms_code_key string|required
     * @LRDresponses 200|400
     *
     * @lrd:start
     * # 개발 중 임시코드 1111
     * @lrd:end
     *
     */
    public function verifySms(Request $request): JsonResponse
    {
        $mobile = $request->input('mobile');
        $sms_code = $request->input('sms_code');
        $sms_code_key = $request->input('sms_code_key');


        if ( $this->verifySmsCode($request) ) {
            return response()->json([
                'message' => '휴대폰 인증번호가 확인되었습니다'
            ], 200);
        }

        return response()->json([
            'message' => '인증번호가 일치하지 않습니다.',
        ], 400);
    }

    private function verifySmsCode(Request $request, $is_verified = false): bool
    {
        $mobile = preg_replace('/[^0-9]/', '', $request->input('mobile'));
        $sms_code = $request->input('sms_code');
        $sms_code_key = $request->input('sms_code_key');

        Log::info('SMS 인증 시도', [
            'mobile' => $mobile,
            'sms_code' => $sms_code,
            'sms_code_key' => $sms_code_key
        ]);

        // 데이터베이스에서 직접 필터링
        $verification = SmsVerification::where('sms_code', $sms_code)
            ->where('sms_code_key', $sms_code_key)
            ->where('expires_at', '>', now())
            ->where('is_verified', $is_verified)
            ->where(function ($query) use ($mobile) {
                $query->whereRaw('REPLACE(REPLACE(mobile, "-", ""), " ", "") = ?', [$mobile]);
            })
            ->first();

        // dd($mobile, $sms_code, $sms_code_key,$verification->toArray());

        if ($verification) {
            if (!$verification->is_verified) {
                $verification->update(['is_verified' => true]);
            }
            Log::info('SMS 인증 성공', [
                'mobile' => $mobile,
                'sms_code' => $sms_code,
                'sms_code_key' => $sms_code_key
            ]);
            return true;
        }

        Log::error('SMS 인증 실패', [
            'mobile' => $mobile,
            'sms_code' => $sms_code,
            'sms_code_key' => $sms_code_key
        ]);
        return false;
    }

    /**
     * 아이디 찾기
     * @LRDparam mobile string|required
     * @LRDresponses 200|400
     */
    public function findTid(Request $request): JsonResponse
    {
        $mobile = preg_replace('/[^0-9]/', '', $request->input('mobile'));

        $user = User::where('mobile', $mobile)->first();

        if (!$user) {
            return response()->json([
                'message' => '존재하지 않는 휴대폰 번호입니다'
            ], 400);
        }

        return response()->json([
            'message' => '아이디가 찾아졌습니다',
            'created_at' => $user->created_at,
            'masked_tid' => strlen($user->tid) <= 3 ?
                substr($user->tid, 0, 1) . '*' . substr($user->tid, -1) :
                substr($user->tid, 0, 2) . str_repeat('*', max(0, strlen($user->tid) - 4)) . substr($user->tid, -2)
        ], 200);
    }

    /**
     * 비밀번호 재설정
     * @LRDparam tid string|required
     * @LRDparam mobile string|required
     * @LRDparam sms_code string|required
     * @LRDparam sms_code_key string|required
     * @LRDparam password string|required
     * @LRDparam password_confirmation string|required
     * @LRDresponses 200|400
     */
    public function setPasswordByVerifySms(Request $request): JsonResponse
    {
        $tid = $request->input('tid');
        $mobile = $request->input('mobile');
        $password = $request->input('password');
        $password_confirmation = $request->input('password_confirmation');

        if ($password !== $password_confirmation) {
            return response()->json([
                'message' => '비밀번호가 일치하지 않습니다.',
            ], 400);
        }

        Log::info('비밀번호 재설정 시도', [
            'tid' => $tid,
            'mobile' => $mobile
        ]);

        // 사용자 확인
        $user = User::where('tid', $tid)
            ->where('mobile', $mobile)
            ->first();

        if (!$user) {
            Log::error('사용자를 찾을 수 없음', [
                'tid' => $tid,
                'mobile' => $mobile
            ]);
            return response()->json([
                'message' => '사용자를 찾을 수 없습니다.'
            ], 400);
        }

        // SMS 인증 확인
        if (!$this->verifySmsCode($request, true)) {
            Log::error('SMS 인증 실패', [
                'tid' => $tid,
                'mobile' => $mobile
            ]);
            return response()->json([
                'message' => '휴대폰 인증번호가 확인되지 않았습니다'
            ], 400);
        }

        DB::transaction(function () use ($user, $password) {
            // 비밀번호 저장 (해시는 모델에서 처리)
            $user->password = $password;
            $user->save();
        });

        // 모든 토큰 무효화 및 새 토큰 발급
        $user->invalidateAllTokens();
        $token = JWTAuth::fromUser($user);
        $refreshToken = $this->createRefreshToken($user);

        Log::info('비밀번호 재설정 성공', [
            'tid' => $tid,
            'mobile' => $mobile
        ]);

        return $this->createTokenResponse($token, $refreshToken->token);
    }

    /**
     * 휴대전화 재설정
     * @LRDparam mobile string|required
     * @LRDparam sms_code string|required
     * @LRDparam sms_code_key string|required
     * @LRDresponses 200|400
     */
    public function setMobile(Request $request): JsonResponse
    {
        $tid = auth()->user()->tid;
        $mobile = $request->input('mobile');

        Log::info('휴대폰 번호 변경 시도', [
            'tid' => $tid,
            'mobile' => $mobile,
            'sms_code' => $request->input('sms_code'),
            'sms_code_key' => $request->input('sms_code_key')
        ]);

        // SMS 인증 확인
        if (!$this->verifySmsCode($request, true)) {
            Log::error('SMS 인증 실패', [
                'tid' => $tid,
                'mobile' => $mobile
            ]);
            return response()->json([
                'message' => '휴대폰 인증번호가 확인되지 않았습니다'
            ], 400);
        }

        DB::transaction(function () use ($tid, $mobile) {
            $user = User::where('tid', $tid)->first();
            $user->mobile = $mobile;
            $user->save();
        });

        // 모든 토큰 무효화 및 새 토큰 발급
        $user = User::where('tid', $tid)->first();

        $user->invalidateAllTokens();
        $token = JWTAuth::fromUser($user);
        $refreshToken = $this->createRefreshToken($user);

        Log::info('휴대폰 번호 변경 성공', [
            'tid' => $tid,
            'mobile' => $mobile
        ]);

        return $this->createTokenResponse($token, $refreshToken->token);
    }

    /**
     * 비밀번호 재설정
     * @LRDparam password string|required
     * @LRDparam new_password string|required
     * @LRDparam new_password_confirmation string|required
     * @LRDresponses 200|400
     */
    public function setPassword(Request $request): JsonResponse
    {
        $tid = auth()->user()->tid;
        $password = $request->input('password');
        $new_password = $request->input('new_password');
        $new_password_confirmation = $request->input('new_password_confirmation');

        // 비밀번호 null 체크
        if (empty($new_password)) {
            return response()->json([
                'message' => '새 비밀번호를 입력해주세요.',
            ], 400);
        }

        // 비밀번호 확인 검증
        if ($new_password !== $new_password_confirmation) {
            return response()->json([
                'message' => '새 비밀번호가 일치하지 않습니다.',
            ], 400);
        }

        // tid 와 기존 password 확인
        $user = User::where('tid', $tid)->first();
        if (!$user || !Hash::check($password, $user->password)) {
            return response()->json([
                'message' => '아이디 또는 비밀번호가 일치하지 않습니다.',
            ], 400);
        }

        // 모델의 setPasswordAttribute를 사용하여 비밀번호 변경
        DB::transaction(function () use ($user, $new_password) {
            $user->password = $new_password;
            $user->save();
        });

        // 모든 토큰 무효화 및 새 토큰 발급
        $user->invalidateAllTokens();
        $token = JWTAuth::fromUser($user);
        $refreshToken = $this->createRefreshToken($user);

        return $this->createTokenResponse($token, $refreshToken->token);
    }

    /**
     * 회원가입 필드 유효성 검사
     *
     * @lrd:start
     * # 요청 예시
     * ```json
     * {
     *     "tid": "testuser",
     *     "mobile": "01012345678",
     *     "password": "password123",
     *     "password_confirmation": "password123",
     *     "name": "홍길동",
     *     "email": "test@example.com",
     *     "type": "owner",
     *     "biz_no": "1234567890"
     * }
     * ```
     *
     * # 응답 예시
     * ## 성공 (200)
     * ```json
     * {
     *     "message": "모든 입력값이 유효합니다."
     * }
     * ```
     *
     * ## 실패 (422)
     * ```json
     * {
     *     "message": "이미 사용 중인 아이디입니다.", (첫번째 에러)
     *     "errors": {
     *         "tid": ["이미 사용 중인 아이디입니다."],
     *         "mobile": ["유효하지 않은 휴대전화 번호입니다."],
     *         "password": ["비밀번호는 최소 8자 이상이어야 합니다."]
     *     }
     * }
     * ```
     *
     * # 참고사항
     * - 모든 필드는 선택적으로 검사 가능합니다.
     * - 전달된 필드만 유효성을 검사합니다.
     * - 비밀번호는 password_confirmation과 함께 전달해야 합니다.
     * @lrd:end
     *
     * @LRDresponses 200|422
     */
    public function registerValidate(Request $request): JsonResponse
    {
        $registerRequest = new RegisterRequest();
        $rules = $registerRequest->rules();
        $messages = $registerRequest->messages();

        // Request에서 들어온 필드만 유효성 검사
        $data = $request->only(array_keys($request->all()));
        $partialRules = array_intersect_key($rules, $data);

        $validator = Validator::make($data, $partialRules, $messages);

        if ($validator->fails()) {
            return response()->json([
                'message' => $validator->errors()->first(),
                'errors' => $validator->errors()
            ], 422);
        }

        return response()->json([
            'message' => '모든 입력값이 유효합니다.'
        ]);
    }

    // 탈퇴기능 추가
    /**
     * 탈퇴
     * @LRDparam message string|nullable 탈퇴 사유
     * @LRDresponses 200|400
     */
    public function withdraw(Request $request): JsonResponse
    {
        $tid = auth()->user()->tid;
        $message = $request->input('message');

        DB::transaction(function () use ($tid) {
            $user = User::where('tid', $tid)->first();
            $user->delete();
        });

        return response()->json([
            'message' => '탈퇴가 완료되었습니다.'
        ], 200);
    }

    /**
     * 로그
     * @LRDparam log JSON Object|required
     * @LRDresponses 200|500
     */
    public function log(Request $request): JsonResponse
    {
        try {
            $user = auth()->user();
            $log = $request->input('log');

            \App\Models\Activity::log(
                $user,
                'LOG',
                $log,
                "{$user->tid} : LOG"
            );

            return response()->json([
                'message' => '로그가 저장되었습니다.'
            ], 200);
        } catch (\Throwable $th) {
            return response()->json([
                'message' => '로그 저장 실패',
                'error' => $th->getMessage()
            ], 500);
        }
    }

}

