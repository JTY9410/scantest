<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\SoftDeletes;
use Illuminate\Support\Facades\Log;

/**
 * @property int $id
 * @property int $user_id
 * @property string $token
 * @property \Illuminate\Support\Carbon $expires_at
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property \Illuminate\Support\Carbon|null $deleted_at
 * @property-read \App\Models\User $user
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken onlyTrashed()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken whereDeletedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken whereExpiresAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken whereToken($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken whereUserId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken withTrashed(bool $withTrashed = true)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|RefreshToken withoutTrashed()
 * @mixin \Eloquent
 */
class RefreshToken extends Model
{
    use SoftDeletes;

    protected $fillable = [
        'user_id',
        'token',
        'expires_at',
    ];

    protected $casts = [
        'expires_at' => 'datetime',
        'deleted_at' => 'datetime',
    ];

    protected static function booted(): void
    {
        static::deleting(function (RefreshToken $refreshToken) {
            $context = [
                'refresh_token_id' => $refreshToken->id,
                'user_id' => $refreshToken->user_id,
                'token' => substr($refreshToken->token, 0, 10) . '...',
                'expires_at' => $refreshToken->expires_at?->toISOString(),
            ];

            // request가 있을 때만 추가 (CLI나 큐에서는 null일 수 있음)
            if (app()->runningInConsole() === false && request() !== null) {
                $context['request_url'] = request()->url();
                $context['request_method'] = request()->method();
                $context['user_agent'] = request()->userAgent();
                $context['ip'] = request()->ip();
            } else {
                $context['context'] = 'CLI/Queue';
            }

            $context['tags'] = ['refresh-token-deleted'];

            // Telescope가 있으면 태그 사용, 없으면 일반 로그
            if (method_exists(\Illuminate\Support\Facades\Log::class, 'withTags')) {
                Log::withTags(['refresh-token-deleted'])->info('RefreshToken 소프트 삭제됨', $context);
            } else {
                Log::info('RefreshToken 소프트 삭제됨', $context);
            }
        });
    }

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function isValid(): bool
    {
        return $this->expires_at->isFuture();
    }
}
