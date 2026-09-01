<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Support\Facades\DB;

/**
 * @property int $id
 * @property string $mobile
 * @property string $sms_code
 * @property string $sms_code_key
 * @property \Illuminate\Support\Carbon $expires_at
 * @property bool $is_verified
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereExpiresAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereIsVerified($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereMobile($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereSmsCode($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereSmsCodeKey($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|SmsVerification whereUpdatedAt($value)
 * @mixin \Eloquent
 */
class SmsVerification extends Model
{
    use HasFactory;

    protected $fillable = [
        'mobile',
        'sms_code',
        'sms_code_key',
        'expires_at',
        'is_verified'
    ];

    protected $casts = [
        'expires_at' => 'datetime',
        'is_verified' => 'boolean'
    ];

    /**
     * 새로운 SMS 인증번호를 생성합니다.
     *
     * @param string $mobile 휴대폰 번호
     * @param string $smsCode 인증번호
     * @param string $smsCodeKey 인증 구분 코드
     * @param int $expireMinutes 만료 시간(분)
     * @return SmsVerification
     */
    public static function createVerification(string $mobile, string $smsCode, string $smsCodeKey, int $expireMinutes = 10): SmsVerification
    {
        return DB::transaction(function () use ($mobile, $smsCode, $smsCodeKey, $expireMinutes) {
            // 기존 인증번호 삭제
            static::where('mobile', $mobile)
                ->where('sms_code_key', $smsCodeKey)
                ->delete();

            // 새로운 인증번호 생성
            return static::create([
                'mobile' => $mobile,
                'sms_code' => $smsCode,
                'sms_code_key' => $smsCodeKey,
                'expires_at' => now()->addMinutes($expireMinutes),
                'is_verified' => false
            ]);
        });
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

}
