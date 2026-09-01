<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Factories\HasFactory;

/**
 * @property int $id
 * @property \Illuminate\Support\Carbon $timestamp 타임스탬프
 * @property int|null $user_id
 * @property string $type 로그 타입
 * @property string $message 로그 메시지
 * @property string|null $desc 추가 텍스트
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property-read \App\Models\User|null $user
 * @method static \Database\Factories\ApplogFactory factory($count = null, $state = [])
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereDesc($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereMessage($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereTimestamp($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Applog whereUserId($value)
 * @mixin \Eloquent
 */
class Applog extends Model
{
    use HasFactory;

    protected $fillable = [
        'timestamp',
        'user_id',
        'user_tid',
        'type',
        'message',
        'desc',
    ];

    protected $casts = [
        'timestamp' => 'datetime:Y-m-d H:i:s.u',
    ];

    public function user()
    {
        return $this->belongsTo(User::class);
    }
}
