<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\SoftDeletes;

/**
 * @property int $id 아이디
 * @property string $type 종류
 * @property int $scan_id 스캔 아이디
 * @property int $code_id 코드 아이디
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property \Illuminate\Support\Carbon|null $deleted_at
 * @property-read \App\Models\Code $code
 * @property-read \App\Models\Scan $scan
 * @method static \Database\Factories\ScanCodeFactory factory($count = null, $state = [])
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode onlyTrashed()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode whereCodeId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode whereDeletedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode whereScanId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode whereType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode withTrashed(bool $withTrashed = true)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|ScanCode withoutTrashed()
 * @mixin \Eloquent
 */
class ScanCode extends Model
{
    use HasFactory, SoftDeletes;

    protected $fillable = [
        'type',
        'scan_id',
        'code_id',
    ];

    protected $casts = [
        'deleted_at' => 'datetime',
    ];

    public function scan()
    {
        return $this->belongsTo(Scan::class);
    }

    public function code()
    {
        return $this->belongsTo(Code::class);
    }
}
