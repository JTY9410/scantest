<?php

namespace App\Models;

// use Illuminate\Contracts\Auth\MustVerifyEmail;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\SoftDeletes;
use Illuminate\Foundation\Auth\User as Authenticatable;
use Illuminate\Notifications\Notifiable;
use Laravel\Sanctum\HasApiTokens;
use PHPOpenSourceSaver\JWTAuth\Contracts\JWTSubject;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\DB;

/**
 * @property int $id
 * @property int|null $company_id 기업 아이디
 * @property string $type
 * @property string|null $mobile 휴대전화
 * @property string|null $biz_no 사업자등록번호
 * @property string $tid 로그인 아이디
 * @property string $name 이름
 * @property string|null $email 이메일
 * @property \Illuminate\Support\Carbon|null $email_verified_at 이메일 인증 시간
 * @property string $password 비밀번호
 * @property string|null $remember_token
 * @property int $token_version 토큰 버전
 * @property string|null $api_key API 키
 * @property string|null $api_host 허용 IP 주소
 * @property \Illuminate\Support\Carbon|null $api_expires_at API 키 만료일
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property \Illuminate\Support\Carbon|null $deleted_at
 * @property-read \App\Models\Company|null $company
 * @property-read \Illuminate\Notifications\DatabaseNotificationCollection<int, \Illuminate\Notifications\DatabaseNotification> $notifications
 * @property-read int|null $notifications_count
 * @property-read \Illuminate\Database\Eloquent\Collection<int, \App\Models\RefreshToken> $refreshTokens
 * @property-read int|null $refresh_tokens_count
 * @property-read \Illuminate\Database\Eloquent\Collection<int, \App\Models\Scan> $scans
 * @property-read int|null $scans_count
 * @property-read \Illuminate\Database\Eloquent\Collection<int, \Laravel\Sanctum\PersonalAccessToken> $tokens
 * @property-read int|null $tokens_count
 * @method static \Database\Factories\UserFactory factory($count = null, $state = [])
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User onlyTrashed()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereBizNo($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereCompanyId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereDeletedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereEmail($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereEmailVerifiedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereMobile($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereName($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User wherePassword($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereRememberToken($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereTid($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereTokenVersion($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User withTrashed(bool $withTrashed = true)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|User withoutTrashed()
 * @mixin \Eloquent
 */
class User extends Authenticatable implements JWTSubject
{
    /** @use HasFactory<\Database\Factories\UserFactory> */
    use HasApiTokens, HasFactory, Notifiable, SoftDeletes;

    /**
     * The "booted" method of the model.
     */
    protected static function booted(): void
    {
        static::creating(function ($user) {
            // tid 없을때 이메일로
            if (empty($user->tid)) {
                $user->tid = $user->email;
            }

            Activity::log(
                $user,
                '회원가입',
                $user->toArray(),
                "{$user->tid} : " . request()->input('message')
            );
        });

        // 수정 이벤트 (트랜잭션 내에서 실행)
        static::updating(function ($user) {
            Activity::log(
                $user,
                '수정',
                null,
                request()->input('message')
            );
        });

        // 삭제 이벤트 (트랜잭션 내에서 실행)
        static::deleting(function ($user) {
            Activity::log(
                $user,
                '삭제',
                null,
                request()->input('message')
            );
        });
    }

    /**
     * The attributes that are mass assignable.
     *
     * @var list<string>
     */
    protected $fillable = [
        'company_id',
        'type',
        'name',
        'mobile',
        'biz_no',
        'email',
        'tid',
        'password',
        'token_version',
        'api_key',
        'api_host',
        'api_expires_at',
    ];

    /**
     * The attributes that should be hidden for serialization.
     *
     * @var list<string>
     */
    protected $hidden = [
        'password',
        'remember_token',
        'api_key',
    ];

    /**
     * Get the attributes that should be cast.
     *
     * @return array<string, string>
     */
    protected function casts(): array
    {
        return [
            'email_verified_at' => 'datetime',
            'deleted_at' => 'datetime',
            'mobile' => 'string',
            'api_expires_at' => 'datetime',
        ];
    }

    public function company()
    {
        return $this->belongsTo(Company::class);
    }

    public function scans()
    {
        return $this->hasMany(Scan::class);
    }

    public function refreshTokens()
    {
        return $this->hasMany(RefreshToken::class);
    }

    /**
     * Find the user instance for the given username.
     *
     * @param  string  $username
     * @return \App\Models\User
     */
    public function findForPassport($username)
    {
        return $this->where('tid', $username)->first();
    }

    /**
     * Get the identifier that will be stored in the subject claim of the JWT.
     *
     * @return mixed
     */
    public function getJWTIdentifier()
    {
        return $this->getKey();
    }

    /**
     * Return a key value array, containing any custom claims to be added to the JWT.
     *
     * @return array
     */
    public function getJWTCustomClaims()
    {
        // 최신 토큰 버전을 가져오기 위해 모델을 새로고침
        $this->refresh();

        Log::info('JWT 클레임 생성', [
            'user_id' => $this->id,
            'token_version' => $this->token_version,
        ]);

        return [
            'token_version' => $this->token_version,
        ];
    }

    /**
     * 모든 토큰을 무효화합니다.
     *
     * @return void
     */
    public function invalidateAllTokens(): void
    {
        $refreshTokenCount = $this->refreshTokens()->count();

        Log::info('토큰 무효화 시작', [
            'user_id' => $this->id,
            'current_token_version' => $this->token_version,
            'refresh_tokens_count' => $refreshTokenCount,
        ]);

        // 토큰 버전 증가
        $this->increment('token_version');

        // 최신 데이터로 새로고침
        $this->refresh();

        Log::info('토큰 버전 증가 완료', [
            'user_id' => $this->id,
            'new_token_version' => $this->token_version,
        ]);

        // 리프레시 토큰 삭제
        $deletedCount = 0;
        $this->refreshTokens->each(function ($refreshToken) use (&$deletedCount) {
            $refreshToken->delete();
            $deletedCount++;
        });

        Log::info('리프레시 토큰 삭제 완료', [
            'user_id' => $this->id,
            'deleted_tokens_count' => $deletedCount,
        ]);
    }

    /**
     * 모바일 번호에서 숫자만 추출하여 저장합니다.
     *
     * @param string $value
     * @return void
     */
    public function setMobileAttribute($value)
    {
        $this->attributes['mobile'] = preg_replace('/[^0-9]/', '', $value);
    }

    /**
     * 모바일 번호를 하이픈이 포함된 형식으로 반환합니다.
     *
     * @return string|null
     */
    public function formatMobile()
    {
        $value = $this->attributes['mobile'] ?? null;
        if (empty($value)) {
            return null;
        }
        return preg_replace('/(\d{3})(\d{4})(\d{4})/', '$1-$2-$3', $value);
    }

    /**
     * 사업자등록번호에서 숫자만 추출하여 저장합니다.
     *
     * @param string $value
     * @return void
     */
    public function setBizNoAttribute($value)
    {
        $this->attributes['biz_no'] = preg_replace('/[^0-9]/', '', $value);
    }

    /**
     * 사업자등록번호를 하이픈이 포함된 형식으로 반환합니다.
     *
     * @return string|null
     */
    public function getBizNoAttribute($value)
    {
        if (empty($value)) {
            return null;
        }
        return preg_replace('/(\d{3})(\d{2})(\d{5})/', '$1-$2-$3', $value);
    }

    public function setPasswordAttribute($value)
    {
        $this->attributes['password'] = \Illuminate\Support\Facades\Hash::make($value);
    }

    /**
     * API 키 만료 여부 확인
     *
     * @return bool
     */
    public function isApiKeyExpired(): bool
    {
        if (!$this->api_expires_at) {
            return false; // 만료일 없음 = 무제한
        }
        return $this->api_expires_at->isPast();
    }

    /**
     * IP 허용 여부 확인
     *
     * @param string $ip
     * @return bool
     */
    public function isIpAllowed(string $ip): bool
    {
        if (!$this->api_host) {
            return false; // 허용 IP 미설정 = 차단
        }

        $allowedHosts = array_map('trim', explode(',', $this->api_host));

        if (in_array('*', $allowedHosts)) {
            return true; // 모든 IP 허용
        }

        foreach ($allowedHosts as $host) {
            if ($host === $ip) {
                return true;
            }
            // 와일드카드 지원 (예: 192.168.1.*)
            if (str_ends_with($host, '*')) {
                $prefix = rtrim($host, '*');
                if (str_starts_with($ip, $prefix)) {
                    return true;
                }
            }
        }

        return false;
    }

    /**
     * API 키 생성
     *
     * @return string
     */
    public static function generateApiKey(): string
    {
        return \Illuminate\Support\Str::random(64);
    }
}
