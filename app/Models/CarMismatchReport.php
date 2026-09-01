<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\SoftDeletes;

/**
 * @property int $id 아이디
 * @property int $user_id 신고자
 * @property string $car_no 차량번호
 * @property string $api_vin 조회차대번호
 * @property string $scan_vin 스캔차대번호
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property \Illuminate\Support\Carbon|null $deleted_at
 * @property-read \App\Models\User $user
 * @method static \Database\Factories\CarMismatchReportFactory factory($count = null, $state = [])
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport onlyTrashed()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereApiVin($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereCarNo($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereDeletedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereScanVin($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport whereUserId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport withTrashed(bool $withTrashed = true)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|CarMismatchReport withoutTrashed()
 * @mixin \Eloquent
 */
class CarMismatchReport extends Model
{
    use HasFactory, SoftDeletes;

    protected $fillable = [
        'user_id',
        'car_no',
        'api_vin',
        'scan_vin',
    ];

    public function user()
    {
        return $this->belongsTo(User::class);
    }

    protected static function booted()
    {
        parent::booted();

        static::creating(function ($model) {
            if (auth()->check()) {
                $model->user_id = auth()->id();
            }
        });
    }
}
